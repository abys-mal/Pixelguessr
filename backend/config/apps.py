from django.contrib.admin.apps import AdminConfig


class AdministratorConfig(AdminConfig):
    default_site = "config.admin.AdministratorSite"
