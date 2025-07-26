import json
from channels.generic.websocket import WebsocketConsumer
from asgiref.sync import async_to_sync

class DashboardConsumer(WebsocketConsumer):
    def connect(self):
        self.group_name = "dashboard_updates"
        async_to_sync(self.channel_layer.group_add)(
            self.group_name,
            self.channel_name
        )
        self.accept()
        self.send(text_data=json.dumps({
            'message': 'WebSocket connected!'
        }))

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(
            self.group_name,
            self.channel_name
        )

    def receive(self, text_data):
        # This consumer is primarily for sending updates from the backend
        # It doesn't expect to receive messages from the frontend for now
        pass

    def send_update(self, event):
        message_type = event['message_type']
        data = event['data']

        self.send(text_data=json.dumps({
            'type': message_type,
            'data': data
        }))