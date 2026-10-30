"""Annotation, AI pre-annotation, and issue-report routes."""

import app as app_module

from datetime import datetime
from datetime import timezone
from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import NotFoundError
from elasticsearch.exceptions import TransportError
from flask import current_app
from flask import jsonify
from flask import request
from flask import session
import json
import math

from app import (
    AIServiceError,
    DATA_LABELS,
    can_access_data_source,
    elastic_error_response,
    login_required,
    mask_sensitive_text,
    request_ai_preannotation,
    user_can_access_project,
    write_audit_log,
)


def register_annotation_routes(app):
    @app.put("/api/data-items/<path:item_id>/label")
    @login_required
    def label_data_item(item_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400
        label = payload.get("label")
        task_id = payload.get("task_id")
        has_annotation = "annotation" in payload
        annotation = payload.get("annotation")
        if has_annotation:
            if not isinstance(annotation, dict) or not isinstance(annotation.get("items"), list):
                return jsonify(code=400, message="多模态标注必须包含 items 数组。", data=None), 400
            if len(annotation["items"]) > 1000 or len(
                json.dumps(annotation, ensure_ascii=False).encode("utf-8")
            ) > 100000:
                return jsonify(code=413, message="单条多模态标注超出大小限制。", data=None), 413
            for entry in annotation["items"]:
                if not isinstance(entry, dict):
                    return jsonify(code=400, message="多模态标注项格式无效。", data=None), 400
                kind = entry.get("kind")
                item_label = entry.get("label")
                media_url = entry.get("media_url")
                if (
                    kind not in {"bbox", "polygon", "keypoint", "segment"}
                    or not isinstance(item_label, str)
                    or not item_label.strip()
                    or len(item_label) > 191
                    or not isinstance(media_url, str)
                    or not media_url
                    or len(media_url) > 2000
                ):
                    return jsonify(code=400, message="多模态标注项缺少有效类型、标签或媒体地址。", data=None), 400
                if kind == "segment":
                    start = entry.get("start")
                    end = entry.get("end")
                    if (
                        not isinstance(start, (int, float))
                        or isinstance(start, bool)
                        or not isinstance(end, (int, float))
                        or isinstance(end, bool)
                        or (isinstance(start, float) and not math.isfinite(start))
                        or (isinstance(end, float) and not math.isfinite(end))
                        or start < 0
                        or end <= start
                    ):
                        return jsonify(code=400, message="时间片段的起止时间无效。", data=None), 400
                    continue
                points = entry.get("points")
                valid_point_count = (
                    isinstance(points, list)
                    and (
                        (kind == "bbox" and len(points) == 2)
                        or (kind == "polygon" and len(points) >= 3)
                        or (kind == "keypoint" and len(points) == 1)
                    )
                )
                if not valid_point_count or any(
                    not isinstance(point, dict)
                    or not isinstance(point.get("x"), (int, float))
                    or isinstance(point.get("x"), bool)
                    or not isinstance(point.get("y"), (int, float))
                    or isinstance(point.get("y"), bool)
                    or (
                        isinstance(point["x"], float)
                        and not math.isfinite(point["x"])
                    )
                    or (
                        isinstance(point["y"], float)
                        and not math.isfinite(point["y"])
                    )
                    or not 0 <= point["x"] <= 100
                    or not 0 <= point["y"] <= 100
                    for point in points
                ):
                    return jsonify(code=400, message="图像标注坐标无效。", data=None), 400
        allowed_labels = DATA_LABELS
        task = None
        if task_id is not None:
            if not isinstance(task_id, int) or task_id < 1:
                return jsonify(code=400, message="task_id 必须是正整数。", data=None), 400
            with app_module.get_db().cursor() as cursor:
                cursor.execute(
                    """
                    SELECT dataset_id, label_schema_id, assignee, status
                    FROM annotation_tasks WHERE id = %s
                    """,
                    (task_id,),
                )
                task = cursor.fetchone()
                if task is None:
                    return jsonify(code=404, message="标注任务不存在。", data=None), 404
                cursor.execute(
                    """
                    SELECT assignee FROM task_items
                    WHERE task_id = %s AND item_id = %s
                    """,
                    (task_id, item_id),
                )
                task_item = cursor.fetchone()
                if task_item is None:
                    return jsonify(code=400, message="数据不属于当前标注任务。", data=None), 400
                cursor.execute(
                    "SELECT labels_json FROM label_schemas WHERE id = %s",
                    (task["label_schema_id"],),
                )
                schema = cursor.fetchone()
            if task_item["assignee"] != session["username"]:
                return jsonify(code=403, message="当前任务未分配给你。", data=None), 403
            if task["status"] in {"已完成", "已暂停"}:
                return jsonify(code=409, message="当前任务状态不允许继续标注。", data=None), 409
            if schema is not None:
                allowed_labels = {
                    option["name"]
                    for option in json.loads(schema["labels_json"])
                }
        if label is not None and (
            not isinstance(label, str) or label not in allowed_labels
        ):
            return jsonify(
                code=400,
                message="标注值必须属于当前任务配置的标签体系，或为 null（清除标注）。",
                data=None,
            ), 400

        labeled_at = datetime.now(timezone.utc).isoformat()
        try:
            client = app_module.get_es_client()
            document = client.get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
            source = document.get("_source") or {}
            if not can_access_data_source(source):
                return jsonify(code=403, message="无权访问该项目的数据。", data=None), 403
            if task is not None:
                if task["dataset_id"] != source.get("dataset_id", 1):
                    return jsonify(code=400, message="数据不属于当前任务的数据集。", data=None), 400
            label_changed = not has_annotation or source.get("label") != label
            client.update(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
                script={
                    "lang": "painless",
                    "source": """
                        boolean label_changed = !params.entry.annotation_present ||
                            ctx._source.label != params.entry.label;
                        if (label_changed) {
                            if (ctx._source.label_history == null) {
                                ctx._source.label_history = [];
                            }
                            ctx._source.label_history.add([
                                'label': params.entry.label,
                                'labeled_by': params.entry.labeled_by,
                                'labeled_at': params.entry.labeled_at
                            ]);
                        }
                        if (params.entry.annotation_present) {
                            if (ctx._source.annotation_history == null) {
                                ctx._source.annotation_history = [];
                            }
                            ctx._source.annotation_history.add([
                                'annotation': params.entry.annotation,
                                'changed_by': params.entry.labeled_by,
                                'changed_at': params.entry.labeled_at
                            ]);
                            if (ctx._source.annotation_history.size() > 50) {
                                ctx._source.annotation_history.remove(0);
                            }
                            ctx._source.annotation = params.entry.annotation;
                        }
                        if (label_changed) {
                            if (params.entry.label == null) {
                                ctx._source.remove('label');
                                ctx._source.remove('labeled_by');
                                ctx._source.remove('labeled_at');
                            } else {
                                ctx._source.label = params.entry.label;
                                ctx._source.labeled_by = params.entry.labeled_by;
                                ctx._source.labeled_at = params.entry.labeled_at;
                            }
                        }
                        ctx._source.updated_at = params.entry.labeled_at;
                    """,
                    "params": {
                        "entry": {
                            "label": label,
                            "labeled_by": session["username"],
                            "labeled_at": labeled_at,
                            "annotation_present": has_annotation,
                            "annotation": annotation,
                        }
                    },
                },
                doc_as_upsert=False,
                refresh="wait_for",
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        if task is not None:
            db = app_module.get_db()
            with db.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE task_items SET status = %s
                    WHERE task_id = %s AND item_id = %s
                    """,
                    ("待标注" if label is None else "已标注", task_id, item_id),
                )
                cursor.execute(
                    """
                    SELECT COUNT(*) AS remaining
                    FROM task_items
                    WHERE task_id = %s AND status NOT IN ('已标注', '已跳过')
                    """,
                    (task_id,),
                )
                remaining = cursor.fetchone()["remaining"]
                next_status = "待审核" if remaining == 0 else "标注中"
                cursor.execute(
                    "UPDATE annotation_tasks SET status = %s WHERE id = %s",
                    (next_status, task_id),
                )
            db.commit()
        return jsonify(
            code=0,
            message="标注已保存",
            data={
                "id": str(item_id),
                "label": label,
                "labeled_by": (
                    session["username"] if label_changed else source.get("labeled_by")
                ) if label is not None else None,
                "labeled_at": (
                    labeled_at if label_changed else source.get("labeled_at")
                ) if label is not None else None,
                "annotation": annotation if has_annotation else None,
                "history_entry": (
                    {
                        "label": label,
                        "labeled_by": session["username"],
                        "labeled_at": labeled_at,
                    }
                    if label_changed
                    else None
                ),
            },
        )

    @app.post("/api/data-items/<path:item_id>/pre-annotate")
    @login_required
    def preannotate_data_item(item_id: str):
        payload = request.get_json(silent=True)
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id < 1:
            return jsonify(code=400, message="AI 预标注必须指定有效 task_id。", data=None), 400
        with app_module.get_db().cursor() as cursor:
            cursor.execute(
                """
                SELECT t.dataset_id, t.label_schema_id, t.status, d.project_id
                FROM annotation_tasks t
                JOIN datasets d ON d.id = t.dataset_id
                WHERE t.id = %s
                """,
                (task_id,),
            )
            task = cursor.fetchone()
            if task is None:
                return jsonify(code=404, message="标注任务不存在。", data=None), 404
            if not user_can_access_project(task["project_id"]):
                return jsonify(code=403, message="无权访问该项目任务。", data=None), 403
            cursor.execute(
                """
                SELECT assignee FROM task_items
                WHERE task_id = %s AND item_id = %s
                """,
                (task_id, item_id),
            )
            task_item = cursor.fetchone()
            if task_item is None:
                return jsonify(code=404, message="数据不属于当前标注任务。", data=None), 404
            if task_item["assignee"] != session["username"]:
                return jsonify(code=403, message="当前任务未分配给你。", data=None), 403
            if task["status"] in {"已完成", "已暂停"}:
                return jsonify(code=409, message="当前任务状态不允许请求 AI 预标注。", data=None), 409
            cursor.execute(
                "SELECT labels_json FROM label_schemas WHERE id = %s",
                (task["label_schema_id"],),
            )
            schema = cursor.fetchone()
        if schema is None:
            return jsonify(code=409, message="任务标签体系不存在。", data=None), 409
        try:
            document = app_module.get_es_client().get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        source = document.get("_source") or {}
        if not can_access_data_source(source):
            return jsonify(code=403, message="无权访问该项目的数据。", data=None), 403
        if source.get("dataset_id", 1) != task["dataset_id"]:
            return jsonify(code=400, message="数据不属于当前任务的数据集。", data=None), 400
        content = next(
            (
                source[key]
                for key in ("content", "text", "message", "description")
                if isinstance(source.get(key), str) and source[key].strip()
            ),
            "",
        )
        if not content:
            return jsonify(code=409, message="当前数据没有可供预标注的文本内容。", data=None), 409
        labels = [
            option["name"]
            for option in json.loads(schema["labels_json"])
            if isinstance(option, dict) and isinstance(option.get("name"), str)
        ]
        if not labels:
            return jsonify(code=409, message="任务标签体系没有可用标签。", data=None), 409
        safe_content = (
            mask_sensitive_text(content)
            if current_app.config.get("MASK_SENSITIVE_DATA", True)
            else content
        )
        try:
            suggestion = request_ai_preannotation(safe_content[:12000], labels)
        except AIServiceError as error:
            current_app.logger.warning("AI pre-annotation failed: %s", error)
            return jsonify(code=502, message=str(error), data=None), 502
        write_audit_log(
            "AI 预标注",
            "数据",
            item_id,
            {"task_id": task_id, "model": suggestion["model"]},
        )
        app_module.get_db().commit()
        return jsonify(
            code=0,
            message="AI 已生成建议，请人工确认后保存。",
            data=suggestion,
        )

    @app.post("/api/data-items/<path:item_id>/issues")
    @login_required
    def report_data_item_issue(item_id: str):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(code=400, message="请求体必须是 JSON 对象", data=None), 400

        issue_type = payload.get("type")
        description = payload.get("description")
        if not isinstance(issue_type, str) or issue_type not in {
            "数据异常",
            "标签疑问",
            "其他",
        }:
            return jsonify(code=400, message="请选择有效的异常类型。", data=None), 400
        if not isinstance(description, str) or not description.strip():
            return jsonify(code=400, message="异常说明不能为空。", data=None), 400
        if len(description.strip()) > 500:
            return jsonify(code=400, message="异常说明不能超过 500 个字符。", data=None), 400

        reported_at = datetime.now(timezone.utc).isoformat()
        report = {
            "type": issue_type,
            "description": description.strip(),
            "reported_by": session["username"],
            "reported_at": reported_at,
        }
        try:
            client = app_module.get_es_client()
            document = client.get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
            if not can_access_data_source(document.get("_source") or {}):
                return jsonify(code=403, message="无权提交该项目数据的反馈。", data=None), 403
            client.update(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
                script={
                    "lang": "painless",
                    "source": """
                        if (ctx._source.issue_reports == null) {
                            ctx._source.issue_reports = [];
                        }
                        ctx._source.issue_reports.add(params.report);
                        if (ctx._source.issue_reports.size() > 100) {
                            ctx._source.issue_reports.remove(0);
                        }
                    """,
                    "params": {"report": report},
                },
                doc_as_upsert=False,
                refresh="wait_for",
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        return jsonify(code=0, message="异常反馈已提交。", data=report)
