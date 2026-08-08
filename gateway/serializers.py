from rest_framework import serializers

from .models import (
    AudioUpload,
    Case,
    CaseDocument,
    CalendarEvent,
    EventReminder,
    Invite,
    LawFirm,
    Membership,
    Transcript,
)


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class FirmSerializer(serializers.ModelSerializer):
    class Meta:
        model = LawFirm
        fields = ['id', 'name', 'slug', 'created_at']


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'user_id', 'email', 'first_name', 'last_name', 'role', 'title']


class InviteSerializer(serializers.ModelSerializer):
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invite
        fields = [
            'id', 'email', 'role', 'title', 'status', 'is_open',
            'expires_at', 'created_at',
        ]


class CaseSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(source='documents.count', read_only=True)

    class Meta:
        model = Case
        fields = [
            'id', 'title', 'reference', 'description',
            'document_count', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class CaseDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseDocument
        fields = [
            'id', 'filename', 'content_type', 'size', 'status',
            'chunk_count', 'error', 'created_at',
        ]


class ReminderSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventReminder
        fields = ['id', 'minutes_before', 'method', 'sent']
        read_only_fields = ['id', 'sent']


class CalendarEventSerializer(serializers.ModelSerializer):
    reminders = ReminderSerializer(many=True, required=False)
    owner_email = serializers.EmailField(source='owner.email', read_only=True)

    class Meta:
        model = CalendarEvent
        fields = [
            'id', 'title', 'description', 'location', 'start', 'end',
            'all_day', 'is_shared', 'case', 'owner_email', 'reminders',
            'created_at',
        ]
        read_only_fields = ['id', 'owner_email', 'created_at']

    def validate(self, attrs):
        start = attrs.get('start', getattr(self.instance, 'start', None))
        end = attrs.get('end', getattr(self.instance, 'end', None))
        if start and end and end < start:
            raise serializers.ValidationError('Event end must be after its start.')
        return attrs

    def create(self, validated_data):
        reminders = validated_data.pop('reminders', [])
        event = CalendarEvent.objects.create(**validated_data)
        for reminder in reminders:
            EventReminder.objects.create(event=event, **reminder)
        return event

    def update(self, instance, validated_data):
        reminders = validated_data.pop('reminders', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if reminders is not None:
            instance.reminders.all().delete()
            for reminder in reminders:
                EventReminder.objects.create(event=instance, **reminder)
        return instance


class TranscriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcript
        fields = ['text', 'detected_language', 'segments', 'provider', 'created_at']


class AudioUploadSerializer(serializers.ModelSerializer):
    transcript = TranscriptSerializer(read_only=True)

    class Meta:
        model = AudioUpload
        fields = [
            'id', 'filename', 'content_type', 'size', 'language',
            'status', 'error', 'case', 'transcript', 'created_at',
        ]
