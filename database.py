from tinydb import TinyDB, Query
from datetime import datetime, timedelta
import qrcode
import os
import secrets

db = TinyDB('db.json')
#бд создается при первом запуске main.py
class BaseModel:
    @classmethod
    def get_by_id(cls, doc_id: int):
        return cls.table.get(doc_id=doc_id)

    @classmethod
    def update(cls, doc_id: int, data: dict):
        cls.table.update(data, doc_ids=[doc_id])

    @classmethod
    def get_all(cls):
        return cls.table.all()

    @classmethod
    def truncate(cls):
        cls.table.truncate()

class User(BaseModel):
    table = db.table('users')
    
    @classmethod
    def create(cls, user_id: int, full_name: str, vehicle: str = None):
        if cls.table.get(Query().user_id == user_id):
            return False
        
        qr_id = secrets.randbelow(10**10)
        while cls.table.get(Query().qr_id == qr_id):
            qr_id = secrets.randbelow(10**10)
        
        cls.table.insert({
            'user_id': user_id,
            'full_name': full_name,
            'vehicle': vehicle,
            'qr_id': qr_id,
            'is_active': True,
            'qr_code_path': None,
            'created_at': datetime.now().isoformat()
        })
        return True

    @classmethod
    def generate_qr(cls, user_id: int):
        user = cls.table.get(Query().user_id == user_id)
        if not user:
            return None
        
        qr_data = f"""
            ID: {user['qr_id']}
            ФИО: {user['full_name']}
            ТС: {user['vehicle'] or 'Нет'}
            Дата: {datetime.now().strftime('%d.%m.%Y')}
        """
        qr = qrcode.make(qr_data)
        qr_path = f'qrcodes/user_{user_id}.png'
        os.makedirs('qrcodes', exist_ok=True)
        qr.save(qr_path)
        
        cls.update(user.doc_id, {'qr_code_path': qr_path})
        return qr_path
# --- Новостной раздел ---
class News(BaseModel):
    table = db.table('news')
    
    @classmethod
    def create(cls, title: str, content: str, media_type: str = None, media_id: str = None):
        return cls.table.insert({
            'title': title,
            'content': content,
            'media_type': media_type,
            'media_id': media_id,
            'created_at': datetime.now().isoformat()
        })
    
    @classmethod
    def get_all(cls):
        return cls.table.all()
    
    @classmethod
    def generate_qr(cls, user_id: int):
        user = cls.table.get(Query().user_id == user_id)
        if not user:
            return None
        
        qr_data = f"""
            ID: {user['qr_id']}
            ФИО: {user['full_name']}
            ТС: {user['vehicle'] or 'Нет'}
            Дата: {datetime.now().strftime('%d.%m.%Y')}
        """
        qr = qrcode.make(qr_data)
        qr_path = f'qrcodes/user_{user_id}.png'
        os.makedirs('qrcodes', exist_ok=True)
        qr.save(qr_path)
        
        cls.update(user.doc_id, {'qr_code_path': qr_path})
        return qr_path

    @classmethod
    def toggle_status(cls, doc_id: int):
        user = cls.get_by_id(doc_id)
        cls.update(doc_id, {'is_active': not user['is_active']})

class Employee(BaseModel):
    table = db.table('employees')
    
    @classmethod
    def create(cls, full_name: str, position: str, vehicle: str = None):
        doc_id = cls.table.insert({
            'full_name': full_name,
            'position': position,
            'vehicle': vehicle,
            'is_active': True,
            'created_at': datetime.now().isoformat()
        })
        return doc_id

    @classmethod
    def toggle_status(cls, doc_id: int):
        employee = cls.get_by_id(doc_id)
        cls.update(doc_id, {'is_active': not employee['is_active']})

class Guest(BaseModel):
    table = db.table('guests')
    
    @classmethod
    def create_temp_pass(cls, days_valid: int):
        qr_id = secrets.randbelow(10**10)
        expires_at = datetime.now() + timedelta(days=days_valid)
        
        # Вставляем запись и получаем ID документа
        doc_id = cls.table.insert({
            'qr_id': qr_id,
            'expires_at': expires_at.isoformat(),
            'is_active': True,
            'qr_code_path': None
        })
        
        # Генерируем QR-код
        qr = qrcode.make(f"TEMP PASS ID: {qr_id}")
        qr_path = f'qrcodes/guest_{doc_id}.png'
        os.makedirs('qrcodes', exist_ok=True)  # Создаем папку, если её нет
        qr.save(qr_path)
        
        # Обновляем запись с путём к QR-коду
        cls.update(doc_id, {'qr_code_path': qr_path})
        
        return doc_id, qr_id  # Возвращаем оба значения!
class AccessLog(BaseModel):
    table = db.table('access_logs')
    
    @classmethod
    def log_entry(cls, user_type: str, user_id: int, status: str):
        cls.table.insert({
            'user_type': user_type,
            'user_id': user_id,
            'timestamp': datetime.now().isoformat(),
            'status': status
        })

class PendingRequest(BaseModel):
    table = db.table('pending_requests')
    
    @classmethod
    def create(cls, requester_id: int, pass_id: int, user_type: str):
        return cls.table.insert({
            'requester_id': requester_id,
            'pass_id': pass_id,
            'user_type': user_type,
            'timestamp': datetime.now().isoformat()
        })
    
    @classmethod
    def get_by_pass_id(cls, pass_id: int):
        return cls.table.get(Query().pass_id == pass_id)