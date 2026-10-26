from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='ListenerProfile',fields=[('id',models.BigAutoField(primary_key=True,serialize=False)),('available',models.BooleanField(default=False)),('trained',models.BooleanField(default=False,help_text='Must be approved by a moderator before matching.')),('created_at',models.DateTimeField(auto_now_add=True)),('user',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='amani_listener',to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='SupportConnection',fields=[('id',models.BigAutoField(primary_key=True,serialize=False)),('status',models.CharField(max_length=16,choices=[('pending','Pending'),('active','Active'),('closed','Closed')],default='pending')),('primary',models.BooleanField(default=False)),('created_at',models.DateTimeField(auto_now_add=True)),('listener',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='amani_listening',to=settings.AUTH_USER_MODEL)),('seeker',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='amani_support',to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='SupportMessage',fields=[('id',models.BigAutoField(primary_key=True,serialize=False)),('body',models.TextField(max_length=2500)),('created_at',models.DateTimeField(auto_now_add=True)),('connection',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='messages',to='amani.supportconnection')),('sender',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL))]),
        migrations.CreateModel(name='StorySummary',fields=[('id',models.BigAutoField(primary_key=True,serialize=False)),('text',models.TextField(max_length=3000,blank=True)),('share_primary',models.BooleanField(default=False)),('updated_at',models.DateTimeField(auto_now=True)),('owner',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='amani_story',to=settings.AUTH_USER_MODEL))]),
        migrations.AddConstraint(model_name='supportconnection',constraint=models.UniqueConstraint(fields=('seeker','listener'),name='amani_unique_pair')),
    ]
