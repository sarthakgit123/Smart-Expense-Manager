import os
import sys

# Add project root to path so "finance_tracker" package is importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finance_tracker.settings')

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()