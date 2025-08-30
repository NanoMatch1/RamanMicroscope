from django.urls import path
from . import views

app_name = 'raman'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('api/instrument-status/', views.instrument_status, name='instrument_status'),
    path('api/scan-parameters/', views.scan_parameters, name='scan_parameters'),
    path('api/update-parameters/', views.update_parameters, name='update_parameters'),
    path('api/send-command/', views.send_command, name='send_command'),
    path('api/start-scan/', views.start_scan, name='start_scan'),
    path('api/cancel-scan/', views.cancel_scan, name='cancel_scan'),
    path('api/initialize-hardware/', views.initialize_hardware, name='initialize_hardware'),
]