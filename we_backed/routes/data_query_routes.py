"""Data listing, filtering, and export routes."""

import app as app_module

import base64
import binascii
from elasticsearch.exceptions import ApiError
from elasticsearch.exceptions import NotFoundError
from elasticsearch.exceptions import TransportError
from flask import Response
from flask import current_app
from flask import jsonify
from flask import request
from flask import session
from flask import stream_with_context
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
        client = None
        try:
            client = app_module.create_es_client()
            response = client.search(
                index=current_app.config["ELASTICSEARCH_INDEX"],
                query=query,
                size=1000,
                scroll="2m",
                sort="_doc",
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            if client is not None:
                client.close()
            return elastic_error_response(error)

        fieldnames = [
            "id",
            "content",
            "label",
            "labeled_by",
            "inserted_at",
            "labeled_at",
        ]

        def generate_export():
            nonlocal response
            scroll_id = response.get("_scroll_id")
            try:
                if export_format == "csv":
                    stream = io.StringIO(newline="")
                    csv.DictWriter(stream, fieldnames=fieldnames).writeheader()
                    yield stream.getvalue()

                while True:
                    hits = response["hits"]["hits"]
                    if not hits:
                        break
                    for hit in hits:
                        item = get_data_item(hit)
                        if export_format == "jsonl":
                            yield json.dumps(item, ensure_ascii=False) + "\n"
                        else:
                            stream = io.StringIO(newline="")
                            csv.DictWriter(
                                stream, fieldnames=fieldnames
                            ).writerow({key: item[key] for key in fieldnames})
                            yield stream.getvalue()

                    if not scroll_id:
                        break
                    response = client.scroll(scroll_id=scroll_id, scroll="2m")
                    scroll_id = response.get("_scroll_id", scroll_id)
            finally:
                try:
                    if scroll_id:
                        client.clear_scroll(scroll_id=scroll_id)
                except (ApiError, TransportError, RuntimeError, ValueError):
                    current_app.logger.warning(
                        "Failed to clear Elasticsearch export scroll context."
                    )
                finally:
                    client.close()

        return Response(
            stream_with_context(generate_export()),
            mimetype=(
                "application/x-ndjson; charset=utf-8"
                if export_format == "jsonl"
                else "text/csv; charset=utf-8"
            ),
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
        after_raw = request.args.get("after")
        pit_id = request.args.get("pit_id")
        search_after = None
        if after_raw:
            try:
                encoded_cursor = after_raw.encode("ascii")
                decoded_cursor = base64.urlsafe_b64decode(
                    encoded_cursor + b"=" * (-len(encoded_cursor) % 4)
                )
                search_after = json.loads(decoded_cursor)
            except (
                UnicodeEncodeError,
                UnicodeDecodeError,
                binascii.Error,
                json.JSONDecodeError,
            ):
                return jsonify(code=400, message="分页游标无效。", data=None), 400
            if (
                not isinstance(search_after, list)
                or not search_after
                or len(search_after) > 16
                or not all(
                    value is None
                    or isinstance(value, (str, int, float))
                    and not isinstance(value, bool)
                    for value in search_after
                )
            ):
                return jsonify(code=400, message="分页游标无效。", data=None), 400
        if pit_id is not None and (not pit_id or len(pit_id) > 512):
            return jsonify(code=400, message="分页快照无效。", data=None), 400
        if after_raw and not pit_id:
            return jsonify(code=400, message="分页游标缺少分页快照。", data=None), 400
        if page > 1 and pit_id and not after_raw:
            return jsonify(code=400, message="分页快照缺少分页游标。", data=None), 400
        use_point_in_time = page == 1 or bool(pit_id)
        query = query_body if filters or search_text else {"match_all": {}}
        try:
            client = app_module.get_es_client()
            search_sort = (
                [
                    {
                        "confidence": {
                            "order": "asc",
                            "missing": "_last",
                            "unmapped_type": "float",
                        }
                    }
                ]
                if sort_by == "uncertain"
                else [
                    {
                        field: {
                            "order": "desc",
                            "missing": "_last",
                            "unmapped_type": "date",
                        }
                    }
                    for field in (
                        "inserted_at",
                        "created_at",
                        "@timestamp",
                        "timestamp",
                        "order_date",
                    )
                ]
            )
            search_kwargs = {
                "query": query,
                "size": page_size,
                "track_total_hits": True,
                "sort": search_sort,
            }
            if use_point_in_time:
                if pit_id is None:
                    pit_id = client.open_point_in_time(
                        index=current_app.config["ELASTICSEARCH_INDEX"],
                        keep_alive="5m",
                    )["id"]
                search_kwargs["pit"] = {"id": pit_id, "keep_alive": "5m"}
                search_kwargs["sort"] = [*search_sort, "_shard_doc"]
                if search_after is not None:
                    search_kwargs["search_after"] = search_after
                response = client.search(**search_kwargs)
            else:
                search_kwargs["index"] = current_app.config["ELASTICSEARCH_INDEX"]
                search_kwargs["from_"] = (page - 1) * page_size
                response = client.search(**search_kwargs)
        except (ApiError, TransportError, RuntimeError, ValueError) as error:
            return elastic_error_response(error)
        hits = response["hits"]
        total = hits["total"]
        if isinstance(total, dict):
            total = total["value"]
        response_pit_id = response.get("pit_id", pit_id) if use_point_in_time else None
        next_cursor = None
        if (
            use_point_in_time
            and response_pit_id
            and hits["hits"]
            and page * page_size < total
        ):
            last_sort = hits["hits"][-1].get("sort")
            if not isinstance(last_sort, list):
                current_app.logger.error(
                    "Elasticsearch PIT response is missing sort values."
                )
                return jsonify(
                    code=503, message="无法继续加载下一页，请重试。", data=None
                ), 503
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(last_sort, separators=(",", ":")).encode("utf-8")
            ).decode("ascii").rstrip("=")
        return jsonify(
            code=0,
            message="ok",
            data={
                "items": [get_data_item(hit) for hit in hits["hits"]],
                "total": total,
                "page": page,
                "page_size": page_size,
                "next_cursor": next_cursor,
                "pit_id": response_pit_id,
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
