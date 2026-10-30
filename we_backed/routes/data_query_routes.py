"""Data listing, filtering, and export routes."""

import app as app_module

from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import NotFoundError
from elasticsearch.exceptions import TransportError
from flask import Response
from flask import current_app
from flask import jsonify
from flask import request
from flask import session
import csv
import io
import json

from app import (
    DATA_LABELS,
    accessible_dataset_ids,
    can_access_data_source,
    can_access_dataset,
    elastic_error_response,
    get_data_item,
    login_required,
    role_required,
    scoped_dataset_filter,
    user_can_access_project,
)


def register_data_query_routes(app):
    @app.get("/api/data-items/export")
    @login_required
    @role_required("超级管理员", "项目管理员", "数据分析员")
    def export_data_items():
        export_format = request.args.get("format", "jsonl")
        if export_format not in {"jsonl", "csv"}:
            return jsonify(code=400, message="仅支持 jsonl 或 csv 格式。", data=None), 400
        status = request.args.get("label_status", "all")
        if status not in {"all", "labeled", "unlabeled", *DATA_LABELS}:
            return jsonify(code=400, message="标注筛选值无效。", data=None), 400
        filters = []
        project_filter = scoped_dataset_filter(accessible_dataset_ids())
        if project_filter:
            filters.append(project_filter)
        if status == "labeled":
            filters.append({"exists": {"field": "label"}})
        elif status == "unlabeled":
            filters.append({"bool": {"must_not": [{"exists": {"field": "label"}}]}})
        elif status in DATA_LABELS:
            filters.append({"term": {"label.keyword": status}})
        dataset_id_raw = request.args.get("dataset_id")
        if dataset_id_raw:
            try:
                dataset_id = int(dataset_id_raw)
            except ValueError:
                return jsonify(code=400, message="dataset_id 必须是正整数。", data=None), 400
            if dataset_id < 1:
                return jsonify(code=400, message="dataset_id 必须是正整数。", data=None), 400
            if not can_access_dataset(dataset_id):
                return jsonify(code=403, message="无权导出该数据集。", data=None), 403
            if dataset_id == 1:
                filters.append(
                    {
                        "bool": {
                            "should": [
                                {"term": {"dataset_id": 1}},
                                {"bool": {"must_not": [{"exists": {"field": "dataset_id"}}]}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                )
            else:
                filters.append({"term": {"dataset_id": dataset_id}})
        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=query,
                from_=0,
                size=10000,
                track_total_hits=True,
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        total = response["hits"]["total"]
        if isinstance(total, dict):
            total = total["value"]
        if total > 10000:
            return jsonify(
                code=413,
                message="单次导出最多 10000 条，请先按标注状态筛选。",
                data=None,
            ), 413
        items = [get_data_item(hit) for hit in response["hits"]["hits"]]
        if export_format == "jsonl":
            content = "\n".join(
                json.dumps(item, ensure_ascii=False) for item in items
            )
            mimetype = "application/x-ndjson; charset=utf-8"
        else:
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "id",
                    "content",
                    "label",
                    "labeled_by",
                    "inserted_at",
                    "labeled_at",
                ],
            )
            writer.writeheader()
            writer.writerows(
                {
                    key: item[key]
                    for key in writer.fieldnames
                }
                for item in items
            )
            content = stream.getvalue()
            mimetype = "text/csv; charset=utf-8"
        return Response(
            content,
            mimetype=mimetype,
            headers={
                "Content-Disposition": f'attachment; filename="data-items.{export_format}"'
            },
        )

    @app.get("/api/data-items")
    @login_required
    def list_data_items():
        page_raw = request.args.get("page", "1")
        page_size_raw = request.args.get("page_size", "20")
        try:
            page = int(page_raw)
            page_size = int(page_size_raw)
        except ValueError:
            return jsonify(
                code=400,
                message="page 和 page_size 必须是整数。",
                data=None,
            ), 400
        if page < 1 or page_size < 1 or page_size > 100:
            return jsonify(
                code=400,
                message="page 必须大于 0，page_size 必须在 1 到 100 之间。",
                data=None,
            ), 400
        label_status = request.args.get("label_status", "all")
        if label_status not in {"all", "labeled", "unlabeled", *DATA_LABELS}:
            return jsonify(
                code=400,
                message=(
                    "label_status 必须是 all、labeled、unlabeled、正向、"
                    "负向或中性。"
                ),
                data=None,
            ), 400
        filters = []
        project_filter = scoped_dataset_filter(accessible_dataset_ids())
        if project_filter:
            filters.append(project_filter)
        if label_status == "labeled":
            filters.append({"exists": {"field": "label"}})
        elif label_status == "unlabeled":
            filters.append({"bool": {"must_not": [{"exists": {"field": "label"}}]}})
        elif label_status in DATA_LABELS:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"label": label_status}},
                            {"term": {"label.keyword": label_status}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        dataset_id_raw = request.args.get("dataset_id")
        task_id_raw = request.args.get("task_id")
        if dataset_id_raw is not None and task_id_raw is not None:
            return jsonify(
                code=400,
                message="dataset_id 和 task_id 不能同时使用。",
                data=None,
            ), 400
        if dataset_id_raw is not None:
            try:
                dataset_id = int(dataset_id_raw)
            except ValueError:
                return jsonify(
                    code=400,
                    message="dataset_id 必须是正整数。",
                    data=None,
                ), 400
            if dataset_id < 1:
                return jsonify(
                    code=400,
                    message="dataset_id 必须是正整数。",
                    data=None,
                ), 400
            if not can_access_dataset(dataset_id):
                return jsonify(code=403, message="无权访问该数据集。", data=None), 403
            if dataset_id == 1:
                filters.append(
                    {
                        "bool": {
                            "should": [
                                {"term": {"dataset_id": 1}},
                                {
                                    "bool": {
                                        "must_not": [
                                            {"exists": {"field": "dataset_id"}}
                                        ]
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                )
            else:
                filters.append({"term": {"dataset_id": dataset_id}})
        if task_id_raw is not None:
            try:
                task_id = int(task_id_raw)
            except ValueError:
                return jsonify(code=400, message="task_id 必须是正整数。", data=None), 400
            if task_id < 1:
                return jsonify(code=400, message="task_id 必须是正整数。", data=None), 400
            with app_module.get_db().cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.assignee, d.project_id
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
                if (
                    session.get("role") == "标注员"
                    and task["assignee"] != session["username"]
                ):
                    return jsonify(code=403, message="当前任务未分配给你。", data=None), 403
                cursor.execute(
                    """
                    SELECT item_id FROM task_items
                    WHERE task_id = %s AND status != '已跳过'
                    ORDER BY item_id
                    """,
                    (task_id,),
                )
                task_item_ids = [row["item_id"] for row in cursor.fetchall()]
            if not task_item_ids:
                return jsonify(
                    code=0,
                    message="ok",
                    data={"items": [], "total": 0, "page": page, "page_size": page_size},
                )
            filters.append({"ids": {"values": task_item_ids}})
        search_text = request.args.get("q", "").strip()
        if len(search_text) > 200:
            return jsonify(code=400, message="搜索内容不能超过 200 个字符。", data=None), 400
        query_body = {"bool": {"filter": filters}} if filters else {"bool": {}}
        if search_text:
            query_body["bool"]["must"] = [
                {
                    "bool": {
                        "should": [
                            {"term": {"_id": search_text}},
                            {"match_phrase": {"content": search_text}},
                            {"match_phrase": {"text": search_text}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            ]
        sort_by = request.args.get("sort", "newest")
        if sort_by not in {"newest", "uncertain"}:
            return jsonify(code=400, message="排序方式无效。", data=None), 400
        query = query_body if filters or search_text else {"match_all": {}}
        try:
            response = app_module.get_es_client().search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=query,
                from_=(page - 1) * page_size,
                size=page_size,
                track_total_hits=True,
                sort=(
                    [{"confidence": {"order": "asc", "missing": "_last"}}]
                    if sort_by == "uncertain"
                    else [{"inserted_at": {"order": "desc", "missing": "_last"}}]
                ),
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        hits = response["hits"]
        total = hits["total"]
        if isinstance(total, dict):
            total = total["value"]
        return jsonify(
            code=0,
            message="ok",
            data={
                "items": [get_data_item(hit) for hit in hits["hits"]],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        )

    @app.get("/api/data-items/<path:item_id>")
    @login_required
    def get_data_item_detail(item_id: str):
        try:
            response = app_module.get_es_client().get(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                id=item_id,
            )
        except NotFoundError as error:
            return elastic_error_response(error)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        if not can_access_data_source(response.get("_source") or {}):
            return jsonify(code=403, message="无权访问该项目的数据。", data=None), 403
        return jsonify(code=0, message="ok", data=get_data_item(response))
