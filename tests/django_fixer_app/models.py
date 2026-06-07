from django.db import models


class Contact(models.Model):
    name = models.CharField(max_length=128)
    phone = models.CharField(max_length=32, null=True, blank=True)

    class Meta:
        app_label = "django_fixer_app"
