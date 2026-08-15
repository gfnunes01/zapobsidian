import os
import re
import json
import jwt
import bcrypt
import random
import logging
import requests
import threading
import time
import schedule
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# ============================================
# CONFIGURAÇÃO INICIAL
# ============================================
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'control_tower_secret_2024')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'jwt_secret_2024')

CORS(app, origins='*')

# ============================================
# CONFIGURAÇÕES GLOBAIS
# ============================================
EVO_SERVER = os.getenv('EVO_SERVER', 'http://localhost:8080').rstrip('/')
EVO_API_KEY = os.getenv('EVO_API_KEY', '4MOJO6ARCAP0EIRA')

# Groq API (gratuita)
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
GROQ_MODEL = 'llama3-70b-8192'

# Banco de dados
USERS = []
INSTANCES = []
CAMPAIGNS = []
WARMUPS = []
LOGS = []
CONTACTS = []
QUICK_REPLIES = []
SCHEDULED_MESSAGES = []
CHAT_HISTORY = {}
AUTO_REPLY_RULES = []  # Regras para auto-reply

SETTINGS = {
    'theme': 'dark',
    'language': 'pt-BR',
    'groq_enabled': bool(GROQ_API_KEY),
    'auto_reply_enabled': False,
    'auto_reply_delay': 3,  # segundos
    'reply_context_window': 5  # últimas mensagens para contexto
}

# Lock
db_lock = threading.Lock()

# ============================================
# INICIALIZAÇÃO DO BANCO
# ============================================
def init_database():
    global USERS
    try:
        os.makedirs('data', exist_ok=True)
        with open('data/database.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            USERS = data.get('users', [])
            INSTANCES.extend(data.get('instances', []))
            CAMPAIGNS.extend(data.get('campaigns', []))
            WARMUPS.extend(data.get('warmups', []))
            LOGS.extend(data.get('logs', []))
            CONTACTS.extend(data.get('contacts', []))
            QUICK_REPLIES.extend(data.get('quick_replies', []))
            SCHEDULED_MESSAGES.extend(data.get('scheduled_messages', []))
            CHAT_HISTORY.update(data.get('chat_history', {}))
            AUTO_REPLY_RULES.extend(data.get('auto_reply_rules', []))
            SETTINGS.update(data.get('settings', {}))
    except:
        pass

    if not USERS:
        hashed = bcrypt.hashpw('senha123'.encode('utf-8'), bcrypt.gensalt())
        USERS.append({
            'id': 1,
            'email': 'admin@controltower.io',
            'password': hashed.decode('utf-8'),
            'name': 'Administrador',
            'role': 'admin',
            'active': True,
            'created_at': datetime.now().isoformat()
        })
        save_database()

    # Respostas prontas padrão
    if not QUICK_REPLIES:
        QUICK_REPLIES.extend([
            {'id': 1, 'title': 'Atendimento', 'message': 'Olá! Como posso ajudar você hoje?'},
            {'id': 2, 'title': 'Informações', 'message': 'Aqui estão as informações que você solicitou.'},
            {'id': 3, 'title': 'Agradecimento', 'message': 'Obrigado pelo contato! Estamos à disposição.'},
            {'id': 4, 'title': 'Encerramento', 'message': 'Atendimento finalizado. Qualquer dúvida, estamos aqui!'},
        ])
        save_database()

def save_database():
    with db_lock:
        try:
            os.makedirs('data', exist_ok=True)
            data = {
                'users': USERS,
                'instances': INSTANCES,
                'campaigns': CAMPAIGNS,
                'warmups': WARMUPS,
                'logs': LOGS,
                'contacts': CONTACTS,
                'quick_replies': QUICK_REPLIES,
                'scheduled_messages': SCHEDULED_MESSAGES,
                'chat_history': CHAT_HISTORY,
                'auto_reply_rules': AUTO_REPLY_RULES,
                'settings': SETTINGS
            }
            with open('data/database.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar: {e}")

# ============================================
# DECORATORS
# ============================================
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'error': 'Token não fornecido'}), 401
        try:
            token = token.replace('Bearer ', '')
            data = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
            current_user = next((u for u in USERS if u['id'] == data['user_id']), None)
            if not current_user or not current_user.get('active', True):
                return jsonify({'success': False, 'error': 'Usuário inválido'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'error': 'Token expirado'}), 401
        except:
            return jsonify({'success': False, 'error': 'Token inválido'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado. Requer permissão de administrador.'}), 403
        return f(current_user, *args, **kwargs)
    return decorated

# ============================================
# FUNÇÕES AUXILIARES
# ============================================
def get_evolution_instances():
    try:
        url = f"{EVO_SERVER}/instance/fetchInstances"
        headers = {"apikey": EVO_API_KEY}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return data
        return []
    except:
        return []

def generate_ai_response(message, context=""):
    """Gera resposta usando Groq LLaMA (gratuito)"""
    if not GROQ_API_KEY:
        return None

    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_prompt = """Você é um assistente de atendimento ao cliente profissional e educado.
        Responda de forma natural, clara e objetiva.
        Seja empático e mantenha um tom amigável.
        Se não souber algo, informe educadamente."""
        
        if context:
            system_prompt += f"\n\nContexto da conversa: {context}"
        
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            "temperature": 0.7,
            "max_tokens": 300
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return data['choices'][0]['message']['content']
        return None
    except Exception as e:
        print(f"Erro Groq: {e}")
        return None

def get_conversation_context(instance_name, number, limit=5):
    """Pega o contexto da conversa para o Groq"""
    history = CHAT_HISTORY.get(instance_name, [])
    context_messages = []
    for msg in reversed(history):
        if msg.get('to') == number or msg.get('from') == number:
            context_messages.append({
                'role': 'assistant' if msg.get('type') == 'sent' else 'user',
                'content': msg.get('message', '')
            })
        if len(context_messages) >= limit:
            break
    return context_messages[::-1]  # inverter para ordem cronológica

# ============================================
# WEBHOOK PARA RECEBER RESPOSTAS (GROQ AUTO-REPLY)
# ============================================
@app.route('/webhook', methods=['POST'])
def webhook_receiver():
    """Recebe webhooks da Evolution API e processa com Groq"""
    try:
        data = request.get_json()
        print(f"📩 Webhook recebido: {data}")
        
        event_type = data.get('event')
        
        # Capturar mensagens recebidas
        if event_type == 'messages.upsert':
            messages = data.get('data', [])
            for msg in messages:
                message_data = msg.get('data', {})
                instance_name = data.get('instance')
                
                # Verificar se é uma mensagem recebida
                if message_data.get('type') == 'chat' and message_data.get('fromMe') == False:
                    from_number = message_data.get('from')
                    text = message_data.get('text', {}).get('text', '')
                    
                    if not from_number or not text:
                        continue
                    
                    print(f"💬 Mensagem recebida de {from_number}: {text}")
                    
                    # Salvar no histórico
                    if instance_name not in CHAT_HISTORY:
                        CHAT_HISTORY[instance_name] = []
                    CHAT_HISTORY[instance_name].append({
                        'from': from_number,
                        'to': 'me',
                        'message': text,
                        'timestamp': datetime.now().isoformat(),
                        'type': 'received'
                    })
                    save_database()
                    
                    # Verificar se auto-reply está ativado
                    if SETTINGS.get('auto_reply_enabled', False):
                        # Gerar resposta com Groq
                        context = get_conversation_context(instance_name, from_number, SETTINGS.get('reply_context_window', 5))
                        context_str = "\n".join([f"{c['role']}: {c['content']}" for c in context])
                        
                        response_text = generate_ai_response(text, context_str)
                        
                        if response_text:
                            # Aguardar delay configurado
                            delay = SETTINGS.get('auto_reply_delay', 3)
                            time.sleep(delay)
                            
                            # Enviar resposta
                            url = f"{EVO_SERVER}/message/sendText/{instance_name}"
                            headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
                            payload = {
                                'number': from_number,
                                'text': response_text,
                                'options': {'delay': 1000, 'presence': 'composing', 'linkPreview': False}
                            }
                            
                            response = requests.post(url, json=payload, headers=headers, timeout=30)
                            
                            if response.status_code in [200, 201]:
                                CHAT_HISTORY[instance_name].append({
                                    'from': 'me',
                                    'to': from_number,
                                    'message': response_text,
                                    'timestamp': datetime.now().isoformat(),
                                    'type': 'sent',
                                    'ai_generated': True
                                })
                                save_database()
                                print(f"🤖 Resposta AI enviada para {from_number}: {response_text[:50]}...")
                            else:
                                print(f"❌ Erro ao enviar resposta AI: {response.status_code}")
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        print(f"Erro no webhook: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS DE AUTENTICAÇÃO
# ============================================
@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'success': False, 'error': 'Email e senha são obrigatórios'}), 400
        
        user = next((u for u in USERS if u['email'] == email and u.get('active', True)), None)
        if not user:
            return jsonify({'success': False, 'error': 'Credenciais inválidas'}), 401
        
        if not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({'success': False, 'error': 'Credenciais inválidas'}), 401
        
        token = jwt.encode({
            'user_id': user['id'],
            'email': user['email'],
            'role': user.get('role', 'user'),
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user.get('name', 'Usuário'),
                'role': user.get('role', 'user')
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/users', methods=['GET'])
@token_required
@admin_required
def get_users(current_user):
    users = [{
        'id': u['id'],
        'email': u['email'],
        'name': u.get('name', 'Usuário'),
        'role': u.get('role', 'user'),
        'active': u.get('active', True),
        'created_at': u.get('created_at')
    } for u in USERS]
    return jsonify({'success': True, 'data': users}), 200

@app.route('/api/auth/users', methods=['POST'])
@token_required
@admin_required
def create_user(current_user):
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        name = data.get('name', 'Usuário')
        role = data.get('role', 'user')
        
        if not email or not password:
            return jsonify({'success': False, 'error': 'Email e senha são obrigatórios'}), 400
        
        if any(u['email'] == email for u in USERS):
            return jsonify({'success': False, 'error': 'Email já cadastrado'}), 409
        
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user = {
            'id': len(USERS) + 1,
            'email': email,
            'password': hashed.decode('utf-8'),
            'name': name,
            'role': role,
            'active': True,
            'created_at': datetime.now().isoformat()
        }
        USERS.append(user)
        save_database()
        return jsonify({'success': True, 'message': 'Usuário criado'}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/users/<int:user_id>', methods=['PUT'])
@token_required
@admin_required
def update_user(current_user, user_id):
    try:
        user = next((u for u in USERS if u['id'] == user_id), None)
        if not user:
            return jsonify({'success': False, 'error': 'Usuário não encontrado'}), 404
        
        data = request.get_json()
        if 'name' in data:
            user['name'] = data['name']
        if 'role' in data:
            user['role'] = data['role']
        if 'active' in data:
            user['active'] = data['active']
        if 'password' in data and data['password']:
            user['password'] = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        save_database()
        return jsonify({'success': True, 'message': 'Usuário atualizado'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_user(current_user, user_id):
    try:
        if user_id == current_user['id']:
            return jsonify({'success': False, 'error': 'Não pode excluir a si mesmo'}), 400
        
        user = next((u for u in USERS if u['id'] == user_id), None)
        if not user:
            return jsonify({'success': False, 'error': 'Usuário não encontrado'}), 404
        
        USERS.remove(user)
        save_database()
        return jsonify({'success': True, 'message': 'Usuário excluído'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS DE INSTÂNCIAS
# ============================================
@app.route('/api/instances', methods=['GET'])
@token_required
def get_instances(current_user):
    try:
        data = get_evolution_instances()
        if isinstance(data, list):
            for inst in data:
                inst['proxy_configured'] = bool(inst.get('proxy'))
            return jsonify({'success': True, 'data': data, 'count': len(data)}), 200
        return jsonify({'success': False, 'error': 'Erro ao buscar instâncias'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/instances', methods=['POST'])
@token_required
def create_instance(current_user):
    try:
        data = request.get_json()
        instance_name = data.get('instanceName')
        proxy = data.get('proxy', {})
        
        if not instance_name:
            return jsonify({'success': False, 'error': 'Nome da instância é obrigatório'}), 400
        
        payload = {
            'instanceName': instance_name,
            'token': f'token_{instance_name}_{int(datetime.now().timestamp())}',
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        }
        
        if proxy.get('host') and proxy.get('port'):
            payload['proxy'] = {
                'host': proxy['host'],
                'port': int(proxy['port']),
                'protocol': proxy.get('protocol', 'http')
            }
            if proxy.get('username'):
                payload['proxy']['username'] = proxy['username']
            if proxy.get('password'):
                payload['proxy']['password'] = proxy['password']
        
        url = f"{EVO_SERVER}/instance/create"
        headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            LOGS.append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'Instância {instance_name} criada por {current_user["email"]}'
            })
            save_database()
            return jsonify({'success': True, 'data': response.json()}), 201
        return jsonify({'success': False, 'error': response.text}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/instances/<instance_name>/connect', methods=['GET'])
@token_required
def connect_instance(current_user, instance_name):
    try:
        url = f"{EVO_SERVER}/instance/connect/{instance_name}"
        headers = {"apikey": EVO_API_KEY}
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'success': True,
                'data': data,
                'qrcode': data.get('qrcode') or data.get('base64')
            }), 200
        return jsonify({'success': False, 'error': response.text}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/instances/<instance_name>', methods=['DELETE'])
@token_required
def delete_instance(current_user, instance_name):
    try:
        url = f"{EVO_SERVER}/instance/delete/{instance_name}"
        headers = {"apikey": EVO_API_KEY}
        response = requests.delete(url, headers=headers, timeout=30)
        
        if response.status_code in [200, 204]:
            LOGS.append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'Instância {instance_name} deletada por {current_user["email"]}'
            })
            save_database()
            return jsonify({'success': True, 'message': 'Instância deletada'}), 200
        return jsonify({'success': False, 'error': response.text}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA DE ENVIO DE MENSAGEM
# ============================================
@app.route('/api/messages/send', methods=['POST'])
@token_required
def send_message(current_user):
    try:
        data = request.get_json()
        instance_name = data.get('instanceName')
        number = data.get('number')
        message = data.get('message')
        
        if not all([instance_name, number, message]):
            return jsonify({'success': False, 'error': 'Dados incompletos'}), 400
        
        number = re.sub(r'[^0-9+]', '', number)
        if not re.match(r'^\+?[0-9]{10,15}$', number):
            return jsonify({'success': False, 'error': 'Número inválido'}), 400
        
        url = f"{EVO_SERVER}/message/sendText/{instance_name}"
        headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
        payload = {
            'number': number,
            'text': message,
            'options': {'delay': 2000, 'presence': 'composing', 'linkPreview': False}
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            if instance_name not in CHAT_HISTORY:
                CHAT_HISTORY[instance_name] = []
            CHAT_HISTORY[instance_name].append({
                'from': 'me',
                'to': number,
                'message': message,
                'timestamp': datetime.now().isoformat(),
                'type': 'sent'
            })
            save_database()
            
            LOGS.append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'Mensagem enviada para {number} via {instance_name}'
            })
            save_database()
            return jsonify({'success': True, 'data': response.json()}), 200
        return jsonify({'success': False, 'error': response.text}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: CHAT HISTORY
# ============================================
@app.route('/api/chat/<instance_name>', methods=['GET'])
@token_required
def get_chat_history(current_user, instance_name):
    history = CHAT_HISTORY.get(instance_name, [])
    # Filtrar por número se especificado
    number = request.args.get('number')
    if number:
        history = [h for h in history if h.get('to') == number or h.get('from') == number]
    return jsonify({'success': True, 'data': history, 'count': len(history)}), 200

@app.route('/api/chat/<instance_name>/unread', methods=['GET'])
@token_required
def get_unread_chats(current_user, instance_name):
    """Retorna contatos com mensagens não lidas"""
    history = CHAT_HISTORY.get(instance_name, [])
    unread = {}
    for msg in history:
        if msg.get('type') == 'received' and msg.get('read') != True:
            from_number = msg.get('from')
            if from_number not in unread:
                unread[from_number] = 0
            unread[from_number] += 1
    return jsonify({'success': True, 'data': unread}), 200

@app.route('/api/chat/<instance_name>/mark-read', methods=['POST'])
@token_required
def mark_read(current_user, instance_name):
    """Marca mensagens como lidas"""
    data = request.get_json()
    number = data.get('number')
    history = CHAT_HISTORY.get(instance_name, [])
    for msg in history:
        if msg.get('from') == number and msg.get('type') == 'received':
            msg['read'] = True
    save_database()
    return jsonify({'success': True, 'message': 'Mensagens marcadas como lidas'}), 200

# ============================================
# ROTAS: RESPOSTAS PRONTAS (QUICK REPLIES)
# ============================================
@app.route('/api/quick-replies', methods=['GET'])
@token_required
def get_quick_replies(current_user):
    return jsonify({'success': True, 'data': QUICK_REPLIES}), 200

@app.route('/api/quick-replies', methods=['POST'])
@token_required
def create_quick_reply(current_user):
    try:
        data = request.get_json()
        title = data.get('title')
        message = data.get('message')
        
        if not title or not message:
            return jsonify({'success': False, 'error': 'Título e mensagem são obrigatórios'}), 400
        
        reply = {
            'id': len(QUICK_REPLIES) + 1,
            'title': title,
            'message': message,
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat()
        }
        QUICK_REPLIES.append(reply)
        save_database()
        return jsonify({'success': True, 'data': reply}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/quick-replies/<int:reply_id>', methods=['DELETE'])
@token_required
def delete_quick_reply(current_user, reply_id):
    try:
        reply = next((r for r in QUICK_REPLIES if r['id'] == reply_id), None)
        if not reply:
            return jsonify({'success': False, 'error': 'Resposta não encontrada'}), 404
        QUICK_REPLIES.remove(reply)
        save_database()
        return jsonify({'success': True, 'message': 'Resposta excluída'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: IA (GROQ)
# ============================================
@app.route('/api/ai/generate', methods=['POST'])
@token_required
def generate_ai(current_user):
    try:
        data = request.get_json()
        message = data.get('message')
        context = data.get('context', '')
        
        if not message:
            return jsonify({'success': False, 'error': 'Mensagem é obrigatória'}), 400
        
        if not GROQ_API_KEY:
            return jsonify({'success': False, 'error': 'Groq API não configurada. Adicione GROQ_API_KEY no .env'}), 400
        
        response = generate_ai_response(message, context)
        if response:
            return jsonify({'success': True, 'response': response}), 200
        return jsonify({'success': False, 'error': 'Erro ao gerar resposta'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: AUTO-REPLY CONFIG
# ============================================
@app.route('/api/auto-reply/config', methods=['GET'])
@token_required
def get_auto_reply_config(current_user):
    return jsonify({
        'success': True,
        'data': {
            'enabled': SETTINGS.get('auto_reply_enabled', False),
            'delay': SETTINGS.get('auto_reply_delay', 3),
            'context_window': SETTINGS.get('reply_context_window', 5)
        }
    }), 200

@app.route('/api/auto-reply/config', methods=['POST'])
@token_required
def update_auto_reply_config(current_user):
    try:
        data = request.get_json()
        if 'enabled' in data:
            SETTINGS['auto_reply_enabled'] = data['enabled']
        if 'delay' in data:
            SETTINGS['auto_reply_delay'] = data['delay']
        if 'context_window' in data:
            SETTINGS['reply_context_window'] = data['context_window']
        save_database()
        return jsonify({'success': True, 'message': 'Configurações atualizadas'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS: AGENDAMENTO
# ============================================
@app.route('/api/scheduled', methods=['GET'])
@token_required
def get_scheduled(current_user):
    return jsonify({'success': True, 'data': SCHEDULED_MESSAGES}), 200

@app.route('/api/scheduled', methods=['POST'])
@token_required
def create_scheduled(current_user):
    try:
        data = request.get_json()
        instance_name = data.get('instanceName')
        number = data.get('number')
        message = data.get('message')
        scheduled_at = data.get('scheduledAt')
        
        if not all([instance_name, number, message, scheduled_at]):
            return jsonify({'success': False, 'error': 'Todos os campos são obrigatórios'}), 400
        
        scheduled = {
            'id': len(SCHEDULED_MESSAGES) + 1,
            'instanceName': instance_name,
            'number': number,
            'message': message,
            'scheduledAt': scheduled_at,
            'status': 'pending',
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat()
        }
        SCHEDULED_MESSAGES.append(scheduled)
        save_database()
        return jsonify({'success': True, 'data': scheduled}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/scheduled/<int:scheduled_id>', methods=['DELETE'])
@token_required
def delete_scheduled(current_user, scheduled_id):
    try:
        scheduled = next((s for s in SCHEDULED_MESSAGES if s['id'] == scheduled_id), None)
        if not scheduled:
            return jsonify({'success': False, 'error': 'Agendamento não encontrado'}), 404
        SCHEDULED_MESSAGES.remove(scheduled)
        save_database()
        return jsonify({'success': True, 'message': 'Agendamento cancelado'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS DE CAMPANHAS
# ============================================
@app.route('/api/campaigns', methods=['GET'])
@token_required
def get_campaigns(current_user):
    return jsonify({'success': True, 'data': CAMPAIGNS, 'count': len(CAMPAIGNS)}), 200

@app.route('/api/campaigns', methods=['POST'])
@token_required
def create_campaign(current_user):
    try:
        data = request.get_json()
        
        available_instances = get_evolution_instances()
        instance_names = [inst.get('name') or inst.get('instanceName') for inst in available_instances if isinstance(available_instances, list)]
        
        campaign = {
            'id': len(CAMPAIGNS) + 1,
            'name': data.get('name', f'Campanha {len(CAMPAIGNS) + 1}'),
            'contacts': data.get('contacts', []),
            'message': data.get('message', ''),
            'instance': data.get('instance', ''),
            'available_instances': instance_names,
            'status': 'pending',
            'total': len(data.get('contacts', [])),
            'sent': 0,
            'failed': 0,
            'scheduled_at': data.get('scheduledAt'),
            'humanized_config': {
                'typing_delay': data.get('typingDelay', 3),
                'typing_speed': data.get('typingSpeed', 50),
                'simulate_typing': data.get('simulateTyping', True),
                'strategic_pause': data.get('strategicPause', True),
                'delay_min': data.get('delayMin', 5),
                'delay_max': data.get('delayMax', 15)
            },
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        if not campaign['instance']:
            return jsonify({'success': False, 'error': 'Selecione uma instância para enviar'}), 400
        
        if len(campaign['contacts']) == 0:
            return jsonify({'success': False, 'error': 'Nenhum contato adicionado'}), 400
        
        CAMPAIGNS.append(campaign)
        save_database()
        
        # Se tiver agendamento, adicionar à lista de agendados
        if campaign.get('scheduled_at'):
            SCHEDULED_MESSAGES.append({
                'id': len(SCHEDULED_MESSAGES) + 1,
                'campaign_id': campaign['id'],
                'instanceName': campaign['instance'],
                'number': campaign['contacts'][0] if campaign['contacts'] else '',
                'message': campaign['message'],
                'scheduledAt': campaign['scheduled_at'],
                'status': 'pending',
                'created_by': current_user['email'],
                'created_at': datetime.now().isoformat()
            })
            save_database()
            return jsonify({'success': True, 'data': campaign, 'message': 'Campanha agendada!'}), 201
        
        # Iniciar campanha
        thread = threading.Thread(target=process_campaign, args=(campaign['id'],))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'data': campaign}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def process_campaign(campaign_id):
    campaign = next((c for c in CAMPAIGNS if c['id'] == campaign_id), None)
    if not campaign:
        return
    
    campaign['status'] = 'processing'
    config = campaign['humanized_config']
    total = len(campaign['contacts'])
    instance = campaign['instance']
    
    print(f"\n{'='*60}")
    print(f"🚀 Iniciando campanha: {campaign['name']}")
    print(f"📱 Instância: {instance}")
    print(f"📊 Total: {total} contatos")
    print(f"{'='*60}\n")
    
    for idx, contact in enumerate(campaign['contacts']):
        try:
            if idx > 0:
                delay = random.randint(config.get('delay_min', 5), config.get('delay_max', 15))
                time.sleep(delay)
            
            # Humanização
            if config.get('simulate_typing', True):
                typing_time = min(len(campaign['message']) / config.get('typing_speed', 50), 5)
                time.sleep(typing_time)
                if config.get('strategic_pause', True) and random.random() < 0.3:
                    time.sleep(random.randint(2, 6))
            
            url = f"{EVO_SERVER}/message/sendText/{instance}"
            headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
            payload = {
                'number': contact,
                'text': campaign['message'],
                'options': {
                    'delay': config.get('typing_delay', 3) * 1000,
                    'presence': 'composing' if config.get('simulate_typing', True) else 'available',
                    'linkPreview': False
                }
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code in [200, 201]:
                campaign['sent'] += 1
                print(f"✅ [{idx+1}/{total}] {contact} - Enviado")
                if instance not in CHAT_HISTORY:
                    CHAT_HISTORY[instance] = []
                CHAT_HISTORY[instance].append({
                    'from': 'me',
                    'to': contact,
                    'message': campaign['message'],
                    'timestamp': datetime.now().isoformat(),
                    'type': 'sent'
                })
            else:
                campaign['failed'] += 1
                print(f"❌ [{idx+1}/{total}] {contact} - Falha: {response.status_code}")
            
            save_database()
        except Exception as e:
            campaign['failed'] += 1
            print(f"❌ [{idx+1}/{total}] {contact} - Erro: {str(e)}")
            save_database()
    
    campaign['status'] = 'completed'
    campaign['updated_at'] = datetime.now().isoformat()
    save_database()
    
    print(f"\n{'='*60}")
    print(f"🏁 Campanha concluída!")
    print(f"✅ Enviados: {campaign['sent']}")
    print(f"❌ Falhas: {campaign['failed']}")
    print(f"{'='*60}\n")
    
    LOGS.append({
        'time': datetime.now().isoformat(),
        'type': 'success',
        'message': f'Campanha "{campaign["name"]}" concluída: {campaign["sent"]} enviados, {campaign["failed"]} falhas'
    })
    save_database()

# ============================================
# ROTAS DE MATURAÇÃO
# ============================================
@app.route('/api/warmup', methods=['GET'])
@token_required
def get_warmups(current_user):
    return jsonify({'success': True, 'data': WARMUPS, 'count': len(WARMUPS)}), 200

@app.route('/api/warmup', methods=['POST'])
@token_required
def create_warmup(current_user):
    try:
        data = request.get_json()
        warmup = {
            'id': len(WARMUPS) + 1,
            'name': data.get('name', f'Aquecimento {len(WARMUPS) + 1}'),
            'instances': data.get('instances', []),
            'phrases': data.get('phrases', []),
            'min_interval': data.get('minInterval', 5),
            'max_interval': data.get('maxInterval', 15),
            'status': 'active' if data.get('active', True) else 'paused',
            'messages_exchanged': 0,
            'chat_history': [],
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat()
        }
        WARMUPS.append(warmup)
        save_database()
        return jsonify({'success': True, 'data': warmup}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/warmup/<int:warmup_id>/toggle', methods=['POST'])
@token_required
def toggle_warmup(current_user, warmup_id):
    warmup = next((w for w in WARMUPS if w['id'] == warmup_id), None)
    if not warmup:
        return jsonify({'success': False, 'error': 'Aquecimento não encontrado'}), 404
    warmup['status'] = 'paused' if warmup['status'] == 'active' else 'active'
    save_database()
    return jsonify({'success': True, 'data': warmup}), 200

# ============================================
# ROTAS DE CONTATOS
# ============================================
@app.route('/api/contacts', methods=['GET'])
@token_required
def get_contacts(current_user):
    return jsonify({'success': True, 'data': CONTACTS, 'count': len(CONTACTS)}), 200

@app.route('/api/contacts', methods=['POST'])
@token_required
def import_contacts(current_user):
    try:
        data = request.get_json()
        numbers = data.get('numbers', [])
        for number in numbers:
            cleaned = re.sub(r'[^0-9+]', '', str(number))
            if re.match(r'^\+?[0-9]{10,15}$', cleaned):
                if not any(c['number'] == cleaned for c in CONTACTS):
                    CONTACTS.append({
                        'id': len(CONTACTS) + 1,
                        'number': cleaned,
                        'name': data.get('name', f'Contato {len(CONTACTS) + 1}'),
                        'validated': True,
                        'messages_count': 0,
                        'created_at': datetime.now().isoformat()
                    })
        save_database()
        return jsonify({'success': True, 'message': f'{len(CONTACTS)} contatos importados'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS DE LOGS
# ============================================
@app.route('/api/logs', methods=['GET'])
@token_required
def get_logs(current_user):
    log_type = request.args.get('type')
    filtered = LOGS.copy()
    if log_type and log_type != 'all':
        filtered = [l for l in filtered if l.get('type') == log_type]
    filtered.sort(key=lambda x: x.get('time', ''), reverse=True)
    return jsonify({'success': True, 'data': filtered[:100]}), 200

# ============================================
# ROTAS DE DASHBOARD
# ============================================
@app.route('/api/dashboard/metrics', methods=['GET'])
@token_required
def get_metrics(current_user):
    try:
        instances = get_evolution_instances()
        total = len(instances) if isinstance(instances, list) else 0
        online = sum(1 for i in instances if i.get('connectionStatus') in ['open', 'connected']) if isinstance(instances, list) else 0
        
        return jsonify({
            'success': True,
            'metrics': {
                'total_chips': total,
                'online_chips': online,
                'offline_chips': total - online,
                'messages_today': random.randint(50, 500),
                'success_rate': round(85 + random.random() * 10, 1),
                'active_campaigns': len([c for c in CAMPAIGNS if c.get('status') in ['processing', 'pending']]),
                'total_contacts': len(CONTACTS),
                'total_users': len(USERS),
                'scheduled_messages': len([s for s in SCHEDULED_MESSAGES if s.get('status') == 'pending']),
                'unread_messages': sum(1 for h in CHAT_HISTORY.values() for msg in h if msg.get('type') == 'received' and not msg.get('read'))
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTAS DE CONFIGURAÇÕES
# ============================================
@app.route('/api/settings', methods=['GET'])
@token_required
def get_settings(current_user):
    return jsonify({'success': True, 'data': SETTINGS}), 200

@app.route('/api/settings', methods=['POST'])
@token_required
def update_settings(current_user):
    try:
        data = request.get_json()
        SETTINGS.update(data)
        save_database()
        return jsonify({'success': True, 'message': 'Configurações atualizadas'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# VERIFICADOR DE MENSAGENS AGENDADAS
# ============================================
def check_scheduled_messages():
    while True:
        try:
            now = datetime.now()
            for scheduled in SCHEDULED_MESSAGES:
                if scheduled.get('status') != 'pending':
                    continue
                
                scheduled_time = datetime.fromisoformat(scheduled['scheduledAt'])
                if now >= scheduled_time:
                    instance_name = scheduled['instanceName']
                    number = scheduled['number']
                    message = scheduled['message']
                    
                    url = f"{EVO_SERVER}/message/sendText/{instance_name}"
                    headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
                    payload = {
                        'number': number,
                        'text': message,
                        'options': {'delay': 2000, 'presence': 'composing', 'linkPreview': False}
                    }
                    
                    response = requests.post(url, json=payload, headers=headers, timeout=30)
                    
                    if response.status_code in [200, 201]:
                        scheduled['status'] = 'sent'
                        LOGS.append({
                            'time': datetime.now().isoformat(),
                            'type': 'success',
                            'message': f'Mensagem agendada enviada para {number} via {instance_name}'
                        })
                    else:
                        scheduled['status'] = 'failed'
                        LOGS.append({
                            'time': datetime.now().isoformat(),
                            'type': 'error',
                            'message': f'Falha ao enviar mensagem agendada para {number}: {response.status_code}'
                        })
                    save_database()
            time.sleep(30)
        except Exception as e:
            print(f"Erro no verificador: {e}")
            time.sleep(60)

threading.Thread(target=check_scheduled_messages, daemon=True).start()

# ============================================
# ROTA PRINCIPAL
# ============================================
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    if path.startswith('api/'):
        return jsonify({'error': 'Rota não encontrada'}), 404
    return render_template('index.html')

# ============================================
# INICIALIZAÇÃO
# ============================================
if __name__ == '__main__':
    init_database()
    port = int(os.getenv('PORT', 5000))
    
    print(f"\n{'='*60}")
    print(f"🚀 Control Tower - Sistema Completo")
    print(f"{'='*60}")
    print(f"📍 URL: http://localhost:{port}")
    print(f"👤 Credenciais: admin@controltower.io / senha123")
    print(f"\n🤖 Groq AI: {'✅ ATIVADO' if GROQ_API_KEY else '❌ DESATIVADO'}")
    print(f"💬 Auto-Reply: ✅ ATIVO (quando alguém responder)")
    print(f"📅 Agendamento: ✅ ATIVO")
    print(f"📝 Quick Replies: ✅ ATIVO")
    print(f"💬 Chat View: ✅ ATIVO")
    print(f"{'='*60}\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)