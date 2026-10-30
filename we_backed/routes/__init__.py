"""Domain-specific Flask route registrations."""


def register_routes(app):
    from .admin_routes import register_admin_routes
    from .annotation_routes import register_annotation_routes
    from .auth_routes import register_auth_routes
    from .data_query_routes import register_data_query_routes
    from .label_schema_routes import register_label_schema_routes
    from .project_routes import register_project_routes
    from .task_routes import register_task_routes

    register_auth_routes(app)
    register_project_routes(app)
    register_label_schema_routes(app)
    register_task_routes(app)
    register_admin_routes(app)
    register_data_query_routes(app)
    register_annotation_routes(app)
