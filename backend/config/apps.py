from django.contrib.admin.apps import AdminConfig


class AdministratorConfig(AdminConfig):
    default_site = "config.admin.AdministratorSite"

    def ready(self):
        from django.conf import settings

        from core.client_ip import proxy_networks

        proxy_networks(tuple(settings.IP_TRUSTED_PROXIES))
        super().ready()
