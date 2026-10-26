from django.urls import path
from . import views
app_name = "amani"
urlpatterns = [path("listener/toggle/", views.listener_toggle, name="listener_toggle"), path("match/", views.match, name="match"), path("connection/<int:pk>/action/", views.connection_action, name="connection_action"), path("connection/<int:pk>/", views.conversation, name="conversation"), path("connection/<int:pk>/send/", views.send_message, name="send_message"), path("story/", views.save_story, name="save_story"),path("", views.home, name="home"), path("chat/", views.chat, name="chat")]
