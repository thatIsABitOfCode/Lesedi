"""Privacy-conscious, non-clinical support interface; conversations are not stored."""
import json
import logging
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)
SYSTEM = """You are Amani, a warm, grounded emotional-support companion in LESEDI, a South African survivor-controlled safety app. You are an AI, not a human therapist, crisis service, or emergency dispatcher. Respect the person's autonomy. Listen, validate without making unsupported assumptions, ask at most one gentle question, and avoid toxic positivity. Never diagnose, pressure someone to leave/report/confront, or offer definitive legal/medical advice. Avoid asking for names, addresses, identifying information, or details of abuse. Never encourage sharing sensitive evidence. If someone describes immediate danger, self-harm intent, or urgent medical need, encourage contacting local emergency services or a trusted person and seeking real-world professional help. Do not claim any alert has been sent. For the listener mode, coach supportive nonjudgmental language and consent. Keep replies short, empathetic, and practical."""

@login_required
def home(request):
    connections = SupportConnection.objects.filter(Q(seeker=request.user) | Q(listener=request.user)).select_related('seeker','listener').order_by('-created_at')[:30]
    profile = ListenerProfile.objects.filter(user=request.user).first()
    story = StorySummary.objects.filter(owner=request.user).first()
    response = render(request, "amani/home.html", {"ai_available": bool(settings.GROQ_API_KEY), "connections": connections, "listener_profile": profile, "story": story})
    response["Cache-Control"] = "no-store"
    return response

@login_required
@require_POST
def chat(request):
    if len(request.body) > 14000:
        return JsonResponse({"error": "Message too long."}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid message."}, status=400)
    message = data.get("message", "")
    mode = data.get("mode", "listen")
    if not isinstance(message, str) or not message.strip() or len(message) > 2500 or mode not in ("listen", "supporter"):
        return JsonResponse({"error": "Please enter a message of up to 2500 characters."}, status=400)
    if not settings.GROQ_API_KEY:
        return JsonResponse({"error": "AI is not configured yet. Add GROQ_API_KEY to your .env file and restart the server."}, status=503)
    rate_key = "amani-rate:" + str(request.user.pk)
    if not cache.add(rate_key, 1, timeout=60):
        try:
            count = cache.incr(rate_key)
        except ValueError:
            cache.set(rate_key, 1, timeout=60)
            count = 1
        if count > 8:
            return JsonResponse({"error": "Please wait a minute before sending another message."}, status=429)
    prompt = SYSTEM + ("\nMODE: Person wants to be heard; listen rather than problem-solve unless asked." if mode == "listen" else "\nMODE: Help the user practice compassionate listening to someone else.")
    payload = json.dumps({"model": settings.GROQ_MODEL, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": message.strip()}], "temperature": 0.55, "max_tokens": 350}).encode()
    req = urlrequest.Request("https://api.groq.com/openai/v1/chat/completions", data=payload, headers={"Authorization": "Bearer " + settings.GROQ_API_KEY, "Content-Type": "application/json"}, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            result = json.load(resp)
        reply = result["choices"][0]["message"]["content"]
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Empty AI response")
        response = JsonResponse({"reply": reply[:4000]})
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, IndexError) as exc:
        logger.warning("Amani provider unavailable: %s", type(exc).__name__)
        response = JsonResponse({"error": "The AI companion is temporarily unavailable. Please try again later."}, status=502)
    response["Cache-Control"] = "no-store"
    return response

from django.contrib import messages as flash
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from .models import ListenerProfile, SupportConnection, SupportMessage, StorySummary

@login_required
@require_POST
def listener_toggle(request):
    profile, _ = ListenerProfile.objects.get_or_create(user=request.user)
    if not profile.trained:
        flash.warning(request, 'A moderator must approve listener training before you can receive requests.')
    else:
        profile.available = not profile.available
        profile.save(update_fields=['available'])
    return redirect('amani:home')

@login_required
@require_POST
def match(request):
    if SupportConnection.objects.filter(seeker=request.user, status__in=['pending','active']).exists():
        flash.info(request, 'You already have a pending or active listener. Open your connection below.')
        return redirect('amani:home')
    with transaction.atomic():
        profiles = ListenerProfile.objects.select_for_update().filter(available=True, trained=True).exclude(user=request.user).exclude(user__in=SupportConnection.objects.filter(seeker=request.user, status='closed').values('listener_id')).order_by('created_at')
        profile = profiles.first()
        if not profile:
            flash.info(request, 'No approved listeners are available right now. You can use the optional AI companion while waiting, or return later.')
            return redirect('amani:home')
        SupportConnection.objects.create(seeker=request.user, listener=profile.user, status='pending')
    flash.success(request, 'Request sent. Your listener must accept before messaging starts.')
    return redirect('amani:home')

@login_required
@require_POST
def connection_action(request, pk):
    connection = get_object_or_404(SupportConnection, pk=pk)
    action = request.POST.get('action')
    if action == 'accept' and connection.listener_id == request.user.pk and connection.status == 'pending':
        connection.status = 'active'
        connection.save(update_fields=['status'])
    elif action == 'primary' and connection.seeker_id == request.user.pk and connection.status == 'active':
        SupportConnection.objects.filter(seeker=request.user).update(primary=False)
        connection.primary = True
        connection.save(update_fields=['primary'])
    elif action == 'close' and request.user.pk in (connection.seeker_id, connection.listener_id):
        connection.status = 'closed'
        connection.primary = False
        connection.save(update_fields=['status','primary'])
    return redirect('amani:home')

@login_required
@require_POST
def send_message(request, pk):
    connection = get_object_or_404(SupportConnection, pk=pk, status='active')
    if request.user.pk not in (connection.seeker_id, connection.listener_id):
        return JsonResponse({'error':'Not permitted'}, status=403)
    body = request.POST.get('body','').strip()
    # Do not claim that these messages are end-to-end encrypted.
    if 0 < len(body) <= 2500:
        SupportMessage.objects.create(connection=connection, sender=request.user, body=body)
    return redirect('amani:conversation', pk=pk)

@login_required
def conversation(request, pk):
    connection = get_object_or_404(SupportConnection.objects.select_related('seeker','listener'), pk=pk)
    if request.user.pk not in (connection.seeker_id, connection.listener_id):
        return JsonResponse({'error':'Not permitted'}, status=403)
    story = None
    if connection.status == 'active' and connection.seeker_id != request.user.pk:
        story = StorySummary.objects.filter(owner=connection.seeker, share_primary=True).first() if connection.primary else None
    response = render(request,'amani/conversation.html',{'connection':connection,'thread':connection.messages.order_by('created_at')[:200], 'shared_story':story})
    response['Cache-Control'] = 'no-store'
    return response

@login_required
@require_POST
def save_story(request):
    StorySummary.objects.update_or_create(owner=request.user, defaults={'text':request.POST.get('text','')[:3000], 'share_primary':request.POST.get('share_primary') == 'on'})
    return redirect('amani:home')
