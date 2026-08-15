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
import base64
import tempfile
import csv
import io
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, jsonify, request, render_template, send_from_directory, Response
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'zap_obsidian_secret_2024')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'zap_obsidian_jwt_secret_2024')

CORS(app, origins='*')

EVO_SERVER = os.getenv('EVO_SERVER', 'http://localhost:8080').rstrip('/')
EVO_API_KEY = os.getenv('EVO_API_KEY', '4MOJO6ARCAP0EIRA')

PUBLIC_URL = os.getenv('PUBLIC_URL', 'https://uselessly-ravioli-upon.ngrok-free.dev')

# ============================================
# ESTRUTURAS DE DADOS GLOBAIS (APENAS PARA ADMIN)
# ============================================
USERS = []
INSTANCES = []
CAMPAIGNS = []
WARMUPS = []
LOGS = []
CONTACTS = []
QUICK_REPLIES = []
SCHEDULED_MESSAGES = []
CHAT_HISTORY = {}
AUTO_REPLY_RULES = []
CAMPAIGN_FLOWS = []
TEMPLATES = []
CAMPAIGN_PAUSED = {}
FUNIS = []
PLANOS = []

db_lock = threading.Lock()

# ============================================
# PLANOS PADRÃO
# ============================================
PLANOS_PADRAO = {
    'starter': {
        'id': 'starter',
        'nome': 'Starter',
        'max_instancias': 3,
        'max_contatos_por_campanha': 100,
        'max_campanhas_simultaneas': 2,
        'permite_funis': True,
        'permite_midia': True,
        'permite_api': True,
        'dias_trial': 7,
        'preco_mensal': 97.00,
        'descricao': 'Ideal para começar com até 3 instâncias'
    },
    'enterprise': {
        'id': 'enterprise',
        'nome': 'Enterprise',
        'max_instancias': 10,
        'max_contatos_por_campanha': 500,
        'max_campanhas_simultaneas': 10,
        'permite_funis': True,
        'permite_midia': True,
        'permite_api': True,
        'dias_trial': 7,
        'preco_mensal': 297.00,
        'descricao': 'Para empresas com até 10 instâncias'
    },
    'obsidian': {
        'id': 'obsidian',
        'nome': 'Obsidian',
        'max_instancias': 999999,
        'max_contatos_por_campanha': 999999,
        'max_campanhas_simultaneas': 999999,
        'permite_funis': True,
        'permite_midia': True,
        'permite_api': True,
        'dias_trial': 999999,
        'preco_mensal': 997.00,
        'descricao': 'Ilimitado. O poder máximo do sistema.'
    }
}

# ============================================
# ESTRUTURAS DE DADOS POR CLIENTE
# ============================================
CLIENT_DATA_CACHE = {}

def get_cliente_id_from_user(current_user):
    return current_user.get('cliente_id', 'default')

def init_cliente_data(cliente_id):
    if cliente_id not in CLIENT_DATA_CACHE:
        CLIENT_DATA_CACHE[cliente_id] = {
            'users': [],
            'instances': [],
            'campaigns': [],
            'warmups': [],
            'logs': [],
            'contacts': [],
            'quick_replies': [],
            'scheduled_messages': [],
            'chat_history': {},
            'auto_reply_rules': [],
            'campaign_flows': [],
            'templates': [],
            'campaign_paused': {},
            'funis': [],
            'planos': []
        }
    return CLIENT_DATA_CACHE[cliente_id]

def get_cliente_db_path(cliente_id):
    base_path = os.getenv('CLIENT_DATA_PATH', 'data')
    client_dir = os.path.join(base_path, cliente_id)
    os.makedirs(client_dir, exist_ok=True)
    return os.path.join(client_dir, 'database.json')

def load_cliente_data(cliente_id):
    if cliente_id in CLIENT_DATA_CACHE:
        return CLIENT_DATA_CACHE[cliente_id]
    
    db_path = get_cliente_db_path(cliente_id)
    data = init_cliente_data(cliente_id)
    
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
            data.update(loaded)
    except FileNotFoundError:
        save_cliente_data(cliente_id, data)
    except Exception as e:
        print(f"Erro ao carregar dados do cliente {cliente_id}: {e}")
    
    CLIENT_DATA_CACHE[cliente_id] = data
    return data

def save_cliente_data(cliente_id, data=None):
    if data is None:
        data = CLIENT_DATA_CACHE.get(cliente_id)
        if not data:
            return
    
    db_path = get_cliente_db_path(cliente_id)
    try:
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar dados do cliente {cliente_id}: {e}")

def get_client_data(current_user):
    if current_user is None:
        return init_cliente_data('default')
    cliente_id = get_cliente_id_from_user(current_user)
    return load_cliente_data(cliente_id)

def save_client_data(current_user):
    if current_user is None:
        return
    cliente_id = get_cliente_id_from_user(current_user)
    data = CLIENT_DATA_CACHE.get(cliente_id)
    if data:
        save_cliente_data(cliente_id, data)

# ============================================
# FUNÇÕES AUXILIARES
# ============================================
def normalizar_numero(numero):
    if not numero:
        return ''
    return re.sub(r'\D', '', str(numero))

def get_saudacao_por_horario():
    hora = datetime.now().hour
    if 5 <= hora < 12:
        return "Bom dia"
    elif 12 <= hora < 18:
        return "Boa tarde"
    else:
        return "Boa noite"

def process_spintax_avancado(text):
    emojis = ['🚀', '💼', '📌', '✅', '🔹', '✨', '🎯', '📊', '💡', '🔥', '⚡', '🌟']
    pattern = r'\{([^}]+)\}'
    def replace_match(match):
        options = match.group(1).split('|')
        if any(emoji in options for emoji in ['emoji', 'emoji1', 'emoji2', 'emoji3']):
            return random.choice(emojis)
        return random.choice(options).strip()
    result = text
    while re.search(pattern, result):
        result = re.sub(pattern, replace_match, result)
    if '{emoji}' in text:
        result = result.replace('{emoji}', random.choice(emojis))
    return result

def filter_by_user(data_list, current_user):
    if current_user.get('role') == 'admin':
        return data_list
    return [item for item in data_list if item.get('user_id') == current_user['id']]

def get_plano_usuario(user):
    if user.get('role') == 'admin':
        return {
            'id': 'admin',
            'nome': 'Administrador (Ilimitado)',
            'max_instancias': 999999,
            'max_contatos_por_campanha': 999999,
            'max_campanhas_simultaneas': 999999,
            'permite_funis': True,
            'permite_midia': True,
            'permite_api': True,
            'preco_mensal': 0,
            'dias_trial': 999999,
            'descricao': 'Acesso ilimitado a todas as funções',
            'expiracao': None
        }
    plano_id = user.get('plano', 'starter')
    plano = PLANOS_PADRAO.get(plano_id, PLANOS_PADRAO['starter'])
    
    if user.get('expiracao'):
        expiracao = datetime.fromisoformat(user['expiracao'])
        if datetime.now() > expiracao:
            return {
                **plano,
                'expirado': True,
                'max_instancias': 0,
                'max_contatos_por_campanha': 0,
                'max_campanhas_simultaneas': 0,
                'permite_funis': False,
                'permite_midia': False,
                'permite_api': False
            }
    return plano

def verificar_limite_instancias(user, cliente_data=None):
    if user.get('role') == 'admin':
        return True
    plano = get_plano_usuario(user)
    if plano.get('expirado', False):
        return False
    
    if cliente_data is None:
        cliente_data = get_client_data(user)
    
    instancias_usuario = [i for i in cliente_data.get('instances', []) if i.get('user_id') == user['id']]
    return len(instancias_usuario) < plano['max_instancias']

def verificar_limite_campanhas(user, cliente_data=None):
    if user.get('role') == 'admin':
        return True
    plano = get_plano_usuario(user)
    if plano.get('expirado', False):
        return False
    
    if cliente_data is None:
        cliente_data = get_client_data(user)
    
    campanhas_ativas = [
        c for c in cliente_data.get('campaigns', []) 
        if c.get('user_id') == user['id'] 
        and c.get('status') in ['processing', 'pending', 'paused']
    ]
    return len(campanhas_ativas) < plano['max_campanhas_simultaneas']

def executar_renovacao_plano(user_id, dias=30):
    # Busca em todos os clientes
    for cliente_id in os.listdir('data'):
        if not os.path.isdir(os.path.join('data', cliente_id)):
            continue
        cliente_data = load_cliente_data(cliente_id)
        user = next((u for u in cliente_data.get('users', []) if u['id'] == user_id), None)
        if user:
            if user.get('role') == 'admin':
                return True
            if user.get('expiracao'):
                expiracao_atual = datetime.fromisoformat(user['expiracao'])
                if datetime.now() > expiracao_atual:
                    nova_expiracao = datetime.now() + timedelta(days=dias)
                else:
                    nova_expiracao = expiracao_atual + timedelta(days=dias)
            else:
                plano = user.get('plano', 'starter')
                dias_trial = PLANOS_PADRAO.get(plano, {}).get('dias_trial', 7)
                nova_expiracao = datetime.now() + timedelta(days=dias_trial)
            user['expiracao'] = nova_expiracao.isoformat()
            save_cliente_data(cliente_id, cliente_data)
            return True
    return False

# ============================================
# TEMPLATES DE SAUDAÇÃO PARA VARIAÇÃO
# ============================================
TEMPLATES_SAUDACAO = [
    # Template 1 - Formal/Profissional
    """{saudacao}, *{nome}*. Tudo bem? Meu nome é *{recruiter}* e falo em nome da *{empresa}*. Somos parceiros da empresa *{parceira}* e selecionamos o seu currículo para uma *vaga* alinhada ao seu perfil.

Caso tenha interesse, estou à disposição para fornecer mais informações sobre a oportunidade.

Aguardamos seu retorno!""",

    # Template 2 - Informal/Próximo
    """📱 *Olá, {nome}!* Como vai? Meu nome é *{recruiter}* e represento a *{empresa}*. Atuamos em parceria com a *{parceira}* e seu currículo foi selecionado para uma *oportunidade* que se encaixa muito bem ao seu perfil.

Se tiver interesse, ficarei feliz em compartilhar mais detalhes sobre a vaga.

Aguardo seu retorno!
Atenciosamente,
{recruiter}""",

    # Template 3 - Direto/Objetivo
    """{saudacao}, {nome}! Aqui é o *{recruiter}* da *{empresa}*. Estamos com uma vaga em parceria com a *{parceira}* e seu perfil chamou nossa atenção.

Quer saber mais detalhes sobre essa oportunidade? Me dá um retorno aqui que te explico tudo!"""
]

def montar_mensagem_funil_flexivel(etapa_id, dados, funil_id=None, cliente_id='default'):
    cliente_data = load_cliente_data(cliente_id)
    funis = cliente_data.get('funis', [])
    
    if funil_id:
        funil = next((f for f in funis if f['id'] == funil_id), None)
        if not funil and funis:
            funil = funis[0]
    else:
        funil = funis[0] if funis else None
    
    if not funil:
        return None, None
    
    etapa = next((e for e in funil['etapas'] if e['id'] == etapa_id), None)
    if not etapa:
        return None, None
    
    template = etapa.get('template', '')
    delay = etapa.get('delay_apos_resposta', 10)
    nome_etapa = etapa.get('nome', 'Etapa')
    
    # SE FOR A ETAPA DE SAUDAÇÃO, USA TEMPLATE VARIÁVEL
    if etapa_id == 'saudacao':
        dados['saudacao'] = get_saudacao_por_horario()
        # Escolhe um template aleatório da lista
        template = random.choice(TEMPLATES_SAUDACAO)
        print(f"🎯 Template de saudação escolhido: {template[:50]}...")
    
    try:
        mensagem = template.format(**dados)
    except KeyError as e:
        print(f"Erro ao preencher template {etapa_id}: {e}")
        mensagem = template
    
    mensagem_final = process_spintax_avancado(mensagem)
    return mensagem_final, {'delay_apos_resposta': delay, 'etapa_nome': nome_etapa}

# ============================================
# BANCO DE DADOS GLOBAL (APENAS ADMIN)
# ============================================
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
                'campaign_flows': CAMPAIGN_FLOWS,
                'templates': TEMPLATES,
                'campaign_paused': CAMPAIGN_PAUSED,
                'funis': FUNIS,
                'planos': PLANOS
            }
            with open('data/database.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str, ensure_ascii=False)
        except Exception as e:
            print(f"Erro ao salvar: {e}")

def init_database():
    global USERS, FUNIS, INSTANCES, CAMPAIGNS, WARMUPS, LOGS, CONTACTS
    global QUICK_REPLIES, SCHEDULED_MESSAGES, CHAT_HISTORY, AUTO_REPLY_RULES
    global CAMPAIGN_FLOWS, TEMPLATES, CAMPAIGN_PAUSED, PLANOS
    
    try:
        os.makedirs('data', exist_ok=True)
        with open('data/database.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            USERS = data.get('users', [])
            INSTANCES = data.get('instances', [])
            CAMPAIGNS = data.get('campaigns', [])
            WARMUPS = data.get('warmups', [])
            LOGS = data.get('logs', [])
            CONTACTS = data.get('contacts', [])
            QUICK_REPLIES = data.get('quick_replies', [])
            SCHEDULED_MESSAGES = data.get('scheduled_messages', [])
            CHAT_HISTORY = data.get('chat_history', {})
            AUTO_REPLY_RULES = data.get('auto_reply_rules', [])
            CAMPAIGN_FLOWS = data.get('campaign_flows', [])
            TEMPLATES = data.get('templates', [])
            CAMPAIGN_PAUSED = data.get('campaign_paused', {})
            FUNIS = data.get('funis', [])
            PLANOS = data.get('planos', [])
    except Exception as e:
        print(f"Erro ao carregar database: {e}")
    
    if not PLANOS:
        for plano_id, plano in PLANOS_PADRAO.items():
            PLANOS.append(plano)
        save_database()
    
    if not USERS:
        hashed = bcrypt.hashpw('senha123'.encode('utf-8'), bcrypt.gensalt())
        USERS.append({
            'id': 1,
            'email': 'admin@zapobsidian.io',
            'password': hashed.decode('utf-8'),
            'name': 'Administrador',
            'role': 'admin',
            'plano': 'obsidian',
            'active': True,
            'expiracao': None,
            'created_at': datetime.now().isoformat()
        })
        hashed2 = bcrypt.hashpw('demo123'.encode('utf-8'), bcrypt.gensalt())
        USERS.append({
            'id': 2,
            'email': 'demo@zapobsidian.io',
            'password': hashed2.decode('utf-8'),
            'name': 'Usuário Demo',
            'role': 'user',
            'plano': 'starter',
            'active': True,
            'expiracao': (datetime.now() + timedelta(days=7)).isoformat(),
            'created_at': datetime.now().isoformat()
        })
        save_database()
    
    if not FUNIS:
        FUNIS.append({
            'id': 1,
            'user_id': 1,
            'nome': 'Funil Padrão',
            'descricao': 'Funil de recrutamento padrão do sistema',
            'etapas': [
                {'id': 'saudacao', 'nome': 'Saudação', 'template': '{saudacao}, *{nome}*. Tudo bem?\nMeu nome é *{recruiter}* e falo em nome da *{empresa}*. Somos parceiros da empresa *{parceira}* e selecionamos o seu currículo para uma *vaga* alinhada ao seu perfil.\n\nCaso tenha interesse, estou à disposição para fornecer mais informações sobre a oportunidade.\nAguardamos seu retorno!', 'delay_apos_resposta': 8},
                {'id': 'vaga', 'nome': 'Vaga Completa', 'template': '{texto_vaga}', 'delay_apos_resposta': 12},
                {'id': 'cadastro', 'nome': 'Link de Cadastro', 'template': 'Para dar continuidade ao processo, basta se cadastrar no site, baixar nosso app pelo link abaixo e fazer o login:\n👉 {link}\n\nQualquer dúvida, pode me chamar aqui que te ajudo!\nAtenciosamente,\n{recruiter}\nRecruiter', 'delay_apos_resposta': 15},
                {'id': 'verificacao', 'nome': 'Verificação Final', 'template': 'Para liberar o acesso às vagas, faça login com seu CPF e senha e complete a verificação de documentos no seu perfil.\n\nEssa verificação é obrigatória e garante sua legibilidade para as oportunidades de emprego.\nÉ rápido e simples! Assim que for aprovado(a), você já poderá se candidatar.\n\nQualquer dúvida, estamos à disposição.\nSucesso! 💼', 'delay_apos_resposta': 20}
            ],
            'created_by': 'admin@zapobsidian.io',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        })
        save_database()

# ============================================
# FUNÇÕES DE ENVIO (USAM DADOS DO CLIENTE)
# ============================================
def send_humanized_message(instance_name, number, message, etapa_nome=None, delay_manual=None, etapa_atual=None, total_etapas=None, current_user=None):
    try:
        print(f"\n{'='*60}")
        print(f"📤 ENVIANDO MENSAGEM")
        print(f"{'='*60}")
        print(f"📱 Instância: {instance_name}")
        print(f"📱 Destinatário: {number}")
        print(f"📝 Etapa: {etapa_nome or 'N/A'}")
        print(f"💬 Mensagem: {message[:100]}{'...' if len(message) > 100 else ''}")
        print(f"{'='*60}\n")
        
        headers = {"apikey": EVO_API_KEY}
        try:
            check_response = requests.get(f"{EVO_SERVER}/instance/fetchInstances", headers=headers, timeout=5)
            if check_response.status_code == 200:
                instances = check_response.json()
                inst = next((i for i in instances if i.get('name') == instance_name), None)
                if inst:
                    status = inst.get('connectionStatus')
                    owner = inst.get('ownerJid')
                    print(f"📊 Status da instância: {status}")
                    print(f"📊 Owner: {owner}")
                else:
                    print(f"⚠️ Instância {instance_name} não encontrada na Evolution API! Tentando enviar mesmo assim...")
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {str(e)} - Continuando com o envio...")
        
        if delay_manual:
            print(f"⏳ Aguardando {delay_manual}s (delay configurado)...")
            time.sleep(delay_manual)
        else:
            initial_delay = random.randint(2, 5)
            print(f"⏳ Aguardando {initial_delay}s (leitura da mensagem)...")
            time.sleep(initial_delay)
        
        typing_time = min(len(message) / 50, 8)
        print(f"⌨️ Simulando digitação: {typing_time:.1f}s")
        time.sleep(typing_time)
        
        if random.random() < 0.3:
            pause_time = random.randint(2, 6)
            print(f"⏸️ Pausa estratégica: {pause_time}s")
            time.sleep(pause_time)
        
        number_clean = re.sub(r'\D', '', str(number))
        if not number_clean:
            erro = "❌ Número inválido após normalização"
            print(erro)
            if current_user:
                cliente_data = get_client_data(current_user)
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'{erro}: {number}'
                })
                save_client_data(current_user)
            return False, "Número inválido"
        
        if number_clean.startswith('55'):
            number_formatted = number_clean
        else:
            number_formatted = f"55{number_clean}"
        
        print(f"📱 Número formatado: {number_formatted}")
        
        url = f"{EVO_SERVER}/message/sendText/{instance_name}"
        headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
        payload = {
            'number': number_formatted,
            'text': message,
            'options': {'delay': 1500, 'presence': 'composing', 'linkPreview': False}
        }
        
        print(f"📤 Enviando para Evolution API: {url}")
        print(f"📤 Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"📥 Status Code: {response.status_code}")
        print(f"📥 Response: {response.text[:500]}")
        
        if response.status_code in [200, 201]:
            print(f"✅ Mensagem enviada com sucesso para {number_formatted}")
            
            if current_user:
                cliente_data = get_client_data(current_user)
                chat_history = cliente_data.get('chat_history', {})
                if instance_name not in chat_history:
                    chat_history[instance_name] = []
                
                etapa_info = etapa_nome or ''
                if etapa_atual is not None and total_etapas is not None:
                    etapa_info = f"{etapa_nome} ({etapa_atual}/{total_etapas})"
                
                chat_history[instance_name].append({
                    'from': 'me',
                    'to': number_formatted,
                    'message': message,
                    'timestamp': datetime.now().isoformat(),
                    'type': 'sent',
                    'etapa': etapa_info,
                    'status': 'sent',
                    'api_response': response.json()
                })
                cliente_data['chat_history'] = chat_history
                
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'success',
                    'message': f'✅ Mensagem enviada para {number_formatted} via {instance_name} - Etapa: {etapa_info}'
                })
                save_client_data(current_user)
            
            return True, response.json()
        
        erro_msg = f"❌ Falha ao enviar mensagem: Status {response.status_code} - {response.text[:200]}"
        print(erro_msg)
        
        if current_user:
            cliente_data = get_client_data(current_user)
            if response.status_code == 401:
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'🚨 SESSÃO EXPIRADA na instância {instance_name}! Reconecte-a.'
                })
            elif response.status_code == 400 and 'TypeError' in response.text:
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'🚨 ERRO INTERNO NA EVOLUTION API: {response.text[:100]} - Instância {instance_name}'
                })
            else:
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'❌ Falha ao enviar: {erro_msg}'
                })
            save_client_data(current_user)
        
        return False, response.text
        
    except Exception as e:
        erro_msg = f"❌ EXCEÇÃO ao enviar mensagem: {str(e)}"
        print(erro_msg)
        import traceback
        traceback.print_exc()
        
        if current_user:
            cliente_data = get_client_data(current_user)
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'error',
                'message': f'{erro_msg} - Trace: {traceback.format_exc()[:200]}'
            })
            save_client_data(current_user)
        return False, str(e)

def send_media_message(instance_name, number, media_data, caption, media_type='image', current_user=None):
    try:
        print(f"\n{'='*60}")
        print(f"📤 ENVIANDO MÍDIA")
        print(f"{'='*60}")
        print(f"📱 Instância: {instance_name}")
        print(f"📱 Destinatário: {number}")
        print(f"📷 Tipo: {media_type}")
        print(f"💬 Legenda: {caption[:100]}{'...' if len(caption) > 100 else ''}")
        print(f"{'='*60}\n")
        
        if isinstance(media_data, dict):
            media_data = media_data.get('file') or media_data.get('data') or media_data.get('media')
        if not media_data:
            erro = "❌ Nenhum dado de mídia"
            print(erro)
            if current_user:
                cliente_data = get_client_data(current_user)
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': erro
                })
                save_client_data(current_user)
            return False, "Nenhum dado de mídia"
        
        if isinstance(media_data, str) and media_data.startswith('http'):
            media_url = media_data
            print(f"📎 URL da mídia: {media_url}")
        elif isinstance(media_data, str) and ('base64,' in media_data or media_data.startswith('data:')):
            if 'base64,' in media_data:
                base64_part = media_data.split('base64,')[1]
            else:
                base64_part = media_data
            base64_part = re.sub(r'\s', '', base64_part)
            base64_part = re.sub(r'[^A-Za-z0-9+/=]', '', base64_part)
            if len(base64_part) < 10:
                erro = "❌ Base64 inválido"
                print(erro)
                if current_user:
                    cliente_data = get_client_data(current_user)
                    cliente_data['logs'].append({
                        'time': datetime.now().isoformat(),
                        'type': 'error',
                        'message': erro
                    })
                    save_client_data(current_user)
                return False, "Base64 inválido"
            
            image_data = base64.b64decode(base64_part)
            upload_dir = os.path.join('static', 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            ext = 'jpg'
            if media_type == 'video':
                ext = 'mp4'
            elif media_type == 'document':
                ext = 'pdf'
            elif 'png' in str(media_data).lower():
                ext = 'png'
            elif 'gif' in str(media_data).lower():
                ext = 'gif'
            timestamp = int(datetime.now().timestamp())
            filename = f"{timestamp}.{ext}"
            filepath = os.path.join(upload_dir, filename)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            media_url = f"{PUBLIC_URL}/static/uploads/{filename}"
            print(f"📎 Mídia salva em: {filepath}")
        else:
            erro = "❌ Formato de mídia não suportado"
            print(erro)
            if current_user:
                cliente_data = get_client_data(current_user)
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': erro
                })
                save_client_data(current_user)
            return False, "Formato de mídia não suportado"
        
        headers = {"apikey": EVO_API_KEY}
        try:
            check_response = requests.get(f"{EVO_SERVER}/instance/fetchInstances", headers=headers, timeout=5)
            if check_response.status_code == 200:
                instances = check_response.json()
                inst = next((i for i in instances if i.get('name') == instance_name), None)
                if inst:
                    status = inst.get('connectionStatus')
                    print(f"📊 Status da instância {instance_name}: {status}")
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {e} - Continuando com o envio...")
        
        url = f"{EVO_SERVER}/message/sendMedia/{instance_name}"
        payload = {
            'number': number,
            'media': media_url,
            'caption': caption,
            'mediatype': media_type
        }
        
        print(f"📤 Enviando para Evolution API: {url}")
        print(f"📤 Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        
        print(f"📥 Status Code: {response.status_code}")
        print(f"📥 Response: {response.text[:200]}")
        
        if response.status_code in [200, 201]:
            print(f"✅ Mídia enviada com sucesso para {number}")
            
            if current_user:
                cliente_data = get_client_data(current_user)
                chat_history = cliente_data.get('chat_history', {})
                if instance_name not in chat_history:
                    chat_history[instance_name] = []
                chat_history[instance_name].append({
                    'from': 'me',
                    'to': number,
                    'message': caption,
                    'media_type': media_type,
                    'timestamp': datetime.now().isoformat(),
                    'type': 'sent',
                    'status': 'sent'
                })
                cliente_data['chat_history'] = chat_history
                
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'success',
                    'message': f'✅ Mídia ({media_type}) enviada para {number} via {instance_name}'
                })
                save_client_data(current_user)
            return True, response.json()
        
        erro_msg = f"❌ Falha ao enviar mídia: {response.text[:200]}"
        print(erro_msg)
        if current_user:
            cliente_data = get_client_data(current_user)
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'error',
                'message': f'Falha ao enviar mídia: {erro_msg}'
            })
            save_client_data(current_user)
        return False, response.text
    except Exception as e:
        erro_msg = f"❌ EXCEÇÃO ao enviar mídia: {str(e)}"
        print(erro_msg)
        import traceback
        traceback.print_exc()
        if current_user:
            cliente_data = get_client_data(current_user)
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'error',
                'message': f'{erro_msg}'
            })
            save_client_data(current_user)
        return False, str(e)

# ============================================
# TOKEN / AUTENTICAÇÃO
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
            
            cliente_id = data.get('cliente_id', 'default')
            cliente_data = load_cliente_data(cliente_id)
            
            current_user = next((u for u in cliente_data.get('users', []) if u['id'] == data['user_id']), None)
            
            if not current_user or not current_user.get('active', True):
                return jsonify({'success': False, 'error': 'Usuário inválido'}), 401
            
            current_user['cliente_id'] = cliente_id
            
            if current_user.get('role') != 'admin' and current_user.get('expiracao'):
                expiracao = datetime.fromisoformat(current_user['expiracao'])
                if datetime.now() > expiracao:
                    return jsonify({
                        'success': False, 
                        'error': 'Plano expirado. Faça a renovação para continuar usando o sistema.',
                        'plano_expirado': True
                    }), 403
                    
        except Exception as e:
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
# NOTIFICAÇÃO
# ============================================
def send_notification(current_user, message, type='info'):
    try:
        cliente_data = get_client_data(current_user)
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': type,
            'message': f'NOTIFICAÇÃO: {message}'
        })
        save_client_data(current_user)
    except Exception as e:
        print(f"Erro ao enviar notificação: {e}")

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
        
        user_encontrado = None
        cliente_id_encontrado = None
        
        # Busca em todos os clientes
        for cliente_id in os.listdir('data'):
            client_path = os.path.join('data', cliente_id)
            if not os.path.isdir(client_path):
                continue
            
            cliente_data = load_cliente_data(cliente_id)
            user = next((u for u in cliente_data.get('users', []) if u['email'] == email and u.get('active', True)), None)
            
            if user:
                user_encontrado = user
                cliente_id_encontrado = cliente_id
                break
        
        # Se não encontrou em clientes, busca no global
        if not user_encontrado:
            user_encontrado = next((u for u in USERS if u['email'] == email and u.get('active', True)), None)
            if user_encontrado:
                cliente_id_encontrado = 'default'
                # Cria o usuário no cliente default se não existir
                default_data = load_cliente_data('default')
                if not any(u['email'] == email for u in default_data.get('users', [])):
                    default_data['users'].append(user_encontrado.copy())
                    save_cliente_data('default', default_data)
        
        if not user_encontrado:
            return jsonify({'success': False, 'error': 'Credenciais inválidas'}), 401
        
        if not bcrypt.checkpw(password.encode('utf-8'), user_encontrado['password'].encode('utf-8')):
            return jsonify({'success': False, 'error': 'Credenciais inválidas'}), 401
        
        if user_encontrado.get('role') != 'admin' and user_encontrado.get('expiracao'):
            expiracao = datetime.fromisoformat(user_encontrado['expiracao'])
            if datetime.now() > expiracao:
                return jsonify({
                    'success': False, 
                    'error': 'Plano expirado. Faça a renovação para continuar usando.',
                    'plano_expirado': True
                }), 403
        
        token = jwt.encode({
            'user_id': user_encontrado['id'],
            'email': user_encontrado['email'],
            'role': user_encontrado.get('role', 'user'),
            'plano': user_encontrado.get('plano', 'starter'),
            'cliente_id': cliente_id_encontrado,
            'exp': datetime.now(timezone.utc) + timedelta(days=7)
        }, app.config['JWT_SECRET_KEY'], algorithm='HS256')
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user_encontrado['id'],
                'email': user_encontrado['email'],
                'name': user_encontrado.get('name', 'Usuário'),
                'role': user_encontrado.get('role', 'user'),
                'plano': user_encontrado.get('plano', 'starter'),
                'expiracao': user_encontrado.get('expiracao'),
                'cliente_id': cliente_id_encontrado
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/users', methods=['GET'])
@token_required
@admin_required
def get_users(current_user):
    cliente_data = get_client_data(current_user)
    users = [{
        'id': u['id'],
        'email': u['email'],
        'name': u.get('name', 'Usuário'),
        'role': u.get('role', 'user'),
        'plano': u.get('plano', 'starter'),
        'active': u.get('active', True),
        'expiracao': u.get('expiracao'),
        'created_at': u.get('created_at')
    } for u in cliente_data.get('users', [])]
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
        plano = data.get('plano', 'starter')
        
        if not email or not password:
            return jsonify({'success': False, 'error': 'Email e senha são obrigatórios'}), 400
        
        cliente_data = get_client_data(current_user)
        
        if any(u['email'] == email for u in cliente_data.get('users', [])):
            return jsonify({'success': False, 'error': 'Email já cadastrado'}), 409
        
        if plano not in PLANOS_PADRAO:
            return jsonify({'success': False, 'error': 'Plano inválido'}), 400
        
        dias_trial = PLANOS_PADRAO[plano].get('dias_trial', 7)
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        user = {
            'id': len(cliente_data.get('users', [])) + 1,
            'email': email,
            'password': hashed.decode('utf-8'),
            'name': name,
            'role': role,
            'plano': plano,
            'active': True,
            'expiracao': (datetime.now() + timedelta(days=dias_trial)).isoformat(),
            'created_at': datetime.now().isoformat()
        }
        cliente_data['users'].append(user)
        save_client_data(current_user)
        
        return jsonify({'success': True, 'message': 'Usuário criado', 'user': user}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/users/<int:user_id>', methods=['PUT'])
@token_required
@admin_required
def update_user(current_user, user_id):
    try:
        cliente_data = get_client_data(current_user)
        user = next((u for u in cliente_data.get('users', []) if u['id'] == user_id), None)
        if not user:
            return jsonify({'success': False, 'error': 'Usuário não encontrado'}), 404
        
        data = request.get_json()
        if 'name' in data:
            user['name'] = data['name']
        if 'role' in data:
            user['role'] = data['role']
        if 'plano' in data and data['plano'] in PLANOS_PADRAO:
            user['plano'] = data['plano']
            dias_trial = PLANOS_PADRAO[data['plano']].get('dias_trial', 7)
            user['expiracao'] = (datetime.now() + timedelta(days=dias_trial)).isoformat()
        if 'active' in data:
            user['active'] = data['active']
        if 'password' in data and data['password']:
            user['password'] = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        save_client_data(current_user)
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
        
        cliente_data = get_client_data(current_user)
        user = next((u for u in cliente_data.get('users', []) if u['id'] == user_id), None)
        if not user:
            return jsonify({'success': False, 'error': 'Usuário não encontrado'}), 404
        
        cliente_data['users'].remove(user)
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Usuário excluído'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/planos', methods=['GET'])
@token_required
def get_planos(current_user):
    return jsonify({'success': True, 'data': PLANOS_PADRAO}), 200

@app.route('/api/auth/me/plano', methods=['GET'])
@token_required
def get_meu_plano(current_user):
    plano = get_plano_usuario(current_user)
    cliente_data = get_client_data(current_user)
    instancias = [i for i in cliente_data.get('instances', []) if i.get('user_id') == current_user['id']]
    campanhas_ativas = [c for c in cliente_data.get('campaigns', []) if c.get('user_id') == current_user['id'] and c.get('status') in ['processing', 'pending', 'paused']]
    
    dias_restantes = None
    if current_user.get('role') != 'admin' and current_user.get('expiracao'):
        expiracao = datetime.fromisoformat(current_user['expiracao'])
        dias_restantes = max(0, (expiracao - datetime.now()).days)
    
    return jsonify({
        'success': True,
        'data': {
            'plano': plano,
            'dias_restantes': dias_restantes,
            'expiracao': current_user.get('expiracao'),
            'uso': {
                'instancias': len(instancias),
                'max_instancias': plano['max_instancias'],
                'campanhas_ativas': len(campanhas_ativas),
                'max_campanhas': plano['max_campanhas_simultaneas']
            }
        }
    }), 200

@app.route('/api/auth/renovar', methods=['POST'])
@token_required
def renovar_plano_route(current_user):
    try:
        data = request.get_json() or {}
        dias = data.get('dias', 30)
        
        if current_user.get('role') == 'admin':
            return jsonify({'success': True, 'message': 'Admin não precisa renovar'}), 200
        
        if executar_renovacao_plano(current_user['id'], dias):
            return jsonify({
                'success': True,
                'message': f'Plano renovado por mais {dias} dias!',
                'nova_expiracao': current_user.get('expiracao')
            }), 200
        else:
            return jsonify({'success': False, 'error': 'Erro ao renovar plano'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# WEBHOOK
# ============================================
@app.route('/webhook', methods=['POST'])
@app.route('/webhook/<path:subpath>', methods=['POST'])
def webhook_receiver(subpath=None):
    try:
        data = request.get_json()
        print(f"\n{'='*60}")
        print(f"📩 WEBHOOK RECEBIDO em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print(f"📌 Subrota: {subpath or 'raiz'}")
        print(f"{'='*60}\n")
        
        # Log global
        LOGS.append({
            'time': datetime.now().isoformat(),
            'type': 'info',
            'message': f'Webhook recebido ({subpath or "raiz"})'
        })
        save_database()
        
        event_type = data.get('event')
        instance_name = data.get('instance') or data.get('instanceName') or 'default'
        
        if not event_type and subpath:
            event_type = subpath.replace('-', '.')
        
        if event_type in ['messages.upsert', 'messages-upsert', 'message']:
            messages_data = data.get('data', [])
            if isinstance(messages_data, dict):
                messages_data = [messages_data]
            if not messages_data and data.get('message'):
                messages_data = [data]
            
            for msg in messages_data:
                msg_data = msg.get('data', {})
                if not msg_data:
                    msg_data = msg
                if msg_data.get('fromMe') == True:
                    continue
                from_number_raw = msg_data.get('from') or msg_data.get('key', {}).get('remoteJid')
                if not from_number_raw:
                    from_number_raw = msg_data.get('remoteJid')
                if not from_number_raw:
                    continue
                from_number = normalizar_numero(from_number_raw)
                if not from_number:
                    continue
                text = None
                if msg_data.get('text'):
                    text = msg_data.get('text')
                elif msg_data.get('conversation'):
                    text = msg_data.get('conversation')
                elif msg_data.get('message'):
                    message_obj = msg_data['message']
                    if message_obj.get('conversation'):
                        text = message_obj['conversation']
                    elif message_obj.get('extendedTextMessage'):
                        text = message_obj['extendedTextMessage'].get('text')
                if not text:
                    continue
                print(f"💬 RESPOSTA RECEBIDA de {from_number}: {text}")
                
                # Busca em todos os clientes para processar a resposta
                for cliente_id in os.listdir('data'):
                    if not os.path.isdir(os.path.join('data', cliente_id)):
                        continue
                    cliente_data = load_cliente_data(cliente_id)
                    chat_history = cliente_data.get('chat_history', {})
                    if instance_name not in chat_history:
                        chat_history[instance_name] = []
                    chat_history[instance_name].append({
                        'from': from_number,
                        'to': 'me',
                        'message': text,
                        'timestamp': datetime.now().isoformat(),
                        'type': 'received',
                        'read': False
                    })
                    cliente_data['chat_history'] = chat_history
                    save_cliente_data(cliente_id, cliente_data)
                    
                    # BUSCA O ADMIN DO CLIENTE PARA USAR COMO current_user
                    admin_user = next((u for u in cliente_data.get('users', []) if u.get('role') == 'admin'), None)
                    if admin_user:
                        admin_user['cliente_id'] = cliente_id
                    else:
                        # Se não tiver admin, cria um usuário temporário
                        admin_user = {
                            'id': 1,
                            'cliente_id': cliente_id,
                            'role': 'admin',
                            'email': 'system@zapobsidian.io',
                            'name': 'Sistema'
                        }
                    
                    # Processa a resposta para campanhas deste cliente com current_user
                    processar_resposta_lead(instance_name, from_number, text, cliente_id, admin_user)
        
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"❌ Erro no webhook: {e}")
        import traceback
        traceback.print_exc()
        LOGS.append({
            'time': datetime.now().isoformat(),
            'type': 'error',
            'message': f'Erro no webhook: {str(e)}'
        })
        save_database()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# PROCESSAR RESPOSTA DO LEAD (SEM GROQ)
# ============================================================
def processar_resposta_lead(instance_name, numero, texto_resposta, cliente_id='default', current_user=None):
    print(f"🔍 Processando resposta de {numero}: {texto_resposta}")
    
    cliente_data = load_cliente_data(cliente_id)
    texto_lower = texto_resposta.lower().strip()
    
    palavras_desinteresse = [
        'não', 'nao', 'dispenso', 'sem interesse', 'não quero', 'não tenho',
        'já trabalhei', 'não gosto', 'nem', 'dispensado', 'não vou',
        'não me interessa', 'não quero participar', 'não é para mim',
        'mas não', 'já tenho', 'não desejo', 'não estou interessado',
        'não quero receber', 'não quero saber', 'não quero mais', 'não participarei',
        'não vou participar', 'já tenho emprego', 'não quero vaga', 'não quero essa vaga',
        'sem chance', 'não me candidate', 'não quero me candidatar', 'não quero processo',
        'dispenso a vaga', 'não gostei', 'não serve', 'não quero saber mais',
        'já encontrei', 'já estou empregado', 'não é para mim', 'não se aplica',
        'não vou me candidatar', 'não vou me inscrever', 'não vou participar',
        'não tenho interesse', 'não tenho interesse nenhum', 'não quero essa oportunidade',
        'dispenso a oportunidade', 'não é minha área', 'não combina comigo',
        'não tenho perfil', 'já tenho outra vaga', 'já estou em processo',
        'não quero mudar de emprego', 'não quero agora', 'depois',
        'mais tarde', 'não agora', 'sem condições', 'não vai dar',
        'não tenho disponibilidade', 'não posso', 'não consigo',
        'não quero nada', 'não', 'mas não vou', 'agora não',
        'não obrigado', 'não tenho interesse', 'dispensado', 'não quero mais',
        'ja tenho', 'já tenho', 'estou fora', 'tô fora', 'fora',
        'desisto', 'desistir', 'cancelar', 'cancela', 'cancelado',
        'não quero saber', 'não quero receber mais', 'pare de me enviar',
        'para de mandar', 'não me mande mais', 'não me envie mais',
        'remover', 'remova', 'sair', 'quero sair', 'tirar', 'tira',
        'excluir', 'exclua', 'bloquear', 'bloqueia', 'não é pra mim',
        'não serve pra mim', 'não combina', 'não encaixa', 'não bate',
        'não é o que procuro', 'não procuro', 'não estou procurando',
        'não busco', 'não é minha praia', 'sem condições', 'não rola',
        'não vai rolar', 'não dá', 'não da', 'não tem como',
        'impossível', 'inviável', 'não compensa', 'não vale a pena',
        'não vale', 'melhor não', 'melhor deixar', 'deixa pra lá',
        'deixa quieto', 'esquece', 'esqueça', 'larga mão', 'larga mao',
        'já resolvi', 'já decidi', 'já escolhi', 'já tenho outro',
        'já estou em outra', 'já fechei', 'já acertei', 'já encaminhei'
    ]
    
    palavras_duvida = [
        'como', 'qual', 'quando', 'onde', 'por que', 'quanto', 'salário',
        'horário', 'benefícios', 'carga', 'local', 'como funciona', 'o que é',
        'quais são', 'explique', 'não entendi', 'pode repetir', 'me explique',
        'gostaria de entender', 'o que significa', 'quero entender', 'explica',
        'esclarecer', 'tirar dúvida', 'dúvida', 'pq', 'pq?', 'qnd', 'qnt',
        'porque', 'qual é', 'me fale', 'me diga', 'pode me dizer',
        'pode explicar', 'pode esclarecer', 'não ficou claro', 'tenho uma pergunta',
        'pergunta', 'questionamento', 'duvida sobre', 'gostaria de saber',
        'queria entender', 'pode me informar', 'me informe', 'informações sobre',
        'me tira uma dúvida', 'me explica uma coisa', 'uma pergunta',
        'posso perguntar', 'posso fazer uma pergunta', 'gostaria de perguntar',
        'quero perguntar', 'quero saber mais sobre', 'sobre a vaga',
        'sobre o salário', 'sobre os benefícios', 'sobre o horário',
        'sobre a localização', 'como vou fazer', 'como devo fazer',
        'o que preciso fazer', 'quais os requisitos', 'requisitos',
        'exige experiência', 'experiência', 'formação', 'escolaridade',
        'remoto', 'presencial', 'híbrido', 'modelo de trabalho',
        'jornada', 'carga horária', 'turno', 'escala'
    ]
    
    palavras_interesse = [
        'sim', 'vaga', 'tenho interesse sim', 'quero', 'gostaria', 'interesse',
        'tenho', 'queria', 'continuar', 'ok', 'certo', 'gostei', 'continue',
        'claro', 'pode ser', 'tá bom', 'tudo bem', 'perfeito', 'conversar',
        'ótimo', 'bom', 'beleza', 'tranquilo', 'está bem', 'então', 'sim sim',
        'ta', 'tá', 'blz', 'pode', 'vamos', 'vamo', 'bora', 'fechou',
        'fechado', 'valeu', 'show', 'top', 'massa', 'com certeza',
        'claro que sim', 'lógico', 'lógico que sim', 'pode deixar',
        'pode contar', 'pode crer', 'vou querer', 'quero receber',
        'estou interessado', 'quero esta vaga', 'quero essa vaga',
        'quero a vaga', 'quero ver a vaga', 'ver a vaga', 'mande a vaga',
        'envie a vaga', 'me mande a vaga', 'me envie a vaga',
        'receber a vaga', 'quero receber a vaga', 'quero mais informações',
        'gostaria de receber', 'quero a descrição', 'descrição da vaga',
        'detalhes da vaga', 'ver a descrição', 'processo seletivo',
        'quero o processo', 'participar do processo', 'quero participar do processo',
        'quero participar do processo seletivo', 'quero continuar no processo',
        'continuar no processo', 'quero seguir no processo', 'seguir no processo',
        'quero avançar no processo', 'avançar no processo', 'quero fazer o processo',
        'fazer o processo', 'quero a próxima etapa', 'próxima etapa',
        'quero continuar', 'quero avançar', 'quero seguir', 'avançar',
        'próximo', 'próxima', 'seguir', 'ir para próxima', 'próximo passo',
        'qual a próxima', 'pode enviar a próxima', 'quero a próxima etapa',
        'estou pronto', 'pode prosseguir', 'prosseguir', 'segue',
        'segue em frente', 'vamos em frente', 'vamos para a próxima',
        'qual próximo', 'candidatar', 'candidato', 'candidata',
        'quero me candidatar', 'me candidatar', 'quero me inscrever',
        'me inscrever', 'vou me candidatar', 'vou me inscrever',
        'candidatar-me', 'inscrever-me', 'quero concorrer', 'concorrer',
        'quero me candidatar a vaga', 'quero me candidatar agora',
        'candidatar agora', 'quero me inscrever na vaga', 'inscrever na vaga',
        'quero concorrer a vaga', 'quero participar', 'quero participar da vaga',
        'quero participar sim', 'quero sim participar', 'vou participar',
        'estou participando', 'tenho interesse em participar',
        'interesse em participar', 'quero muito participar',
        'quero muito essa vaga', 'quero fazer parte', 'fazer parte',
        'quero fazer parte da empresa', 'quero entrar', 'quero trabalhar',
        'quero fazer parte do time', 'tenho perfil', 'meu perfil combina',
        'combina comigo', 'quero enviar currículo', 'curriculo', 'currículo',
        'enviar curriculo', 'meu currículo combina', 'vou fazer',
        'quero fazer', 'quero entrar', 'manda', 'mande', 'envia',
        'envie', 'encaminha', 'me mande', 'me envie', 'me encaminhe',
        'me passe', 'manda mais', 'envie mais', 'manda tudo', 'envie tudo',
        'quero mais informações', 'me mande mais', 'quero muito',
        'quero muito sim', 'vou sim', 'tô dentro', 'tô interessado',
        'tô querendo', 'estou dentro', 'estou dentro do processo',
        'tô dentro do processo', 'quero essa oportunidade', 'essa oportunidade',
        'gostei da vaga', 'gostei muito da vaga', 'quero essa vaga pra mim',
        'vou dar meu melhor', 'estou disposto', 'disposto a participar',
        'quero muito participar', 'quero muito essa oportunidade',
        'quero muito essa vaga', 'quero muito me candidatar', 'vou me dedicar',
        'quero essa chance', 'essa chance', 'quero essa oportunidade de emprego',
        'oportunidade de emprego', 'pode contar comigo', 'pode crer que sim',
        'certeza', 'tenho certeza', 'com certeza quero', 'lógico que quero',
        'claro que quero', 'sim, quero', 'quero sim', 'vou querer sim',
        'tenho interesse sim', 'estou interessado sim', 'quero participar sim',
        'quero a vaga', 'quero essa vaga', 'quero esta vaga', 'vaga de emprego',
        'essa oportunidade', 'esta oportunidade', 'quero me candidatar a essa vaga',
        'candidatar a essa vaga', 'inscrever nessa vaga', 'me inscrever nessa vaga',
        'processo seletivo dessa vaga', 'processo seletivo desta vaga',
        'quero sim', 'quero participar', 'aceito', 'aceitar', 'topo',
        'topo sim', 'tô dentro', 'estou dentro', 'quero fazer parte',
        'quero trabalhar', 'quero esta oportunidade', 'quero essa chance',
        'quero me candidatar', 'vou me candidatar', 'vou participar',
        'vou tentar', 'quero tentar', 'posso participar', 'posso me candidatar',
        'me inscrevo', 'vou me inscrever', 'quero me inscrever agora',
        'quero entrar no processo', 'entrar no processo', 'fazer parte do processo',
        'quero o link', 'link', 'link de cadastro', 'cadastro', 'me cadastrar',
        'quero me cadastrar', 'vou me cadastrar', 'quero acessar', 'acessar',
        'quero o site', 'site', 'plataforma', 'app', 'quero o app',
        'baixar', 'baixar o app', 'baixar app', 'quero baixar',
        'quero me registrar', 'registrar', 'registro', 'me registrar',
        'criar conta', 'quero criar conta', 'fazer conta', 'abrir conta',
        'quero mais detalhes', 'mais detalhes', 'detalhes completos',
        'informações completas', 'quero tudo', 'tudo sobre a vaga',
        'descrição completa', 'vaga completa', 'texto da vaga',
        'enviar vaga', 'me enviar vaga', 'receber vaga',
        'quero receber agora', 'pode enviar agora', 'manda agora',
        'envia agora', 'quero hoje', 'agora', 'já', 'pode mandar já',
        'pode enviar já', 'estou esperando', 'aguardando', 'esperando',
        'ansioso', 'quero ver', 'mostra', 'mostrar', 'quero visualizar',
        'visualizar', 'quero analisar', 'analisar', 'avaliar', 'quero avaliar',
        'quero conhecer', 'conhecer', 'quero saber', 'saber mais',
        'claro', 'certamente', 'com certeza', 'absolutamente',
        'definitivamente', 'totalmente', 'completamente', 'perfeitamente',
        'excelente', 'maravilha', 'fantástico', 'sensacional', 'incrível',
        'quero muito', 'muito', 'demais', 'super', 'ultra', 'mega',
        'quero sim', 'quero mais', 'quero tudo', 'quero completo',
        'estou preparado', 'preparado', 'pronto', 'preparado para participar',
        'pronto para participar', 'preparado para começar', 'pronto para começar',
        'vamos em frente', 'vamos nessa', 'vamos com tudo', 'partiu',
        'bora lá', 'vamo que vamo', 'vamos que vamos',
        'ok', 'okay', 'blz', 'beleza', 'tranquilo', 'suave', 'de boa',
        'tá', 'ta', 'tá bom', 'ta bom', 'tudo certo', 'certinho',
        'perfeito', 'ótimo', 'excelente', 'maravilha', 'show',
        'top', 'massa', 'da hora', 'legal', 'bacana', 'maneiro',
        'sim', 's', 'ss', 'simsim', 'siim', 'simmmm',
        'simm', 'sim m', 'sim!', 'simm!',
        '👍', '👏', '🙌', '💪', '✌️', '🤝', '🔥', '⚡', '💯',
        '😊', '😁', '😃', '😄', '🙏', '✅', '✔️',
        'obrigado', 'obrigada', 'agradeço', 'grato', 'grata',
        'muito obrigado', 'muito obrigada', 'valeu mesmo', 'agradecido',
        'tenho disponibilidade', 'disponível', 'estou disponível',
        'posso agora', 'agora mesmo', 'já agora', 'no momento',
        'tenho tempo', 'estou livre', 'livre agora', 'pode ser agora',
        'horário flexível', 'flexível', 'posso me adaptar', 'adapto',
        'me encaixo', 'encaixo', 'encaixa no meu horário',
        'tenho experiência', 'experiência', 'já trabalhei', 'conhecimento',
        'tenho conhecimento', 'conheço a área', 'tenho perfil', 'me encaixo',
        'combina comigo', 'é comigo', 'me identifico', 'identificação',
        'gosto da área', 'amo a área', 'quero crescer', 'crescer',
        'desenvolvimento', 'aprender', 'quero aprender', 'quero crescer na empresa',
        'conheço a empresa', 'sei quem é', 'já ouvi falar', 'bem avaliada',
        'bem vista', 'boa empresa', 'quer trabalhar', 'quero estar na empresa',
        'fazer parte do time', 'entrar para o time', 'time',
        'gostei da empresa', 'gostei do perfil', 'interessante',
        'salário justo', 'boa remuneração', 'benefícios bons',
        'vale transporte', 'vale alimentação', 'plano de saúde',
        'plano odontológico', 'bonificações', 'comissões',
        'participação nos lucros', 'plr', 'incentivos'
    ]
    
    # ============ CORREÇÃO: ADICIONEI 'scheduled' AOS STATUS ============
    campanhas_ativas = [
        c for c in cliente_data.get('campaigns', []) 
        if c.get('instance') == instance_name 
        and c.get('status') in ['processing', 'paused', 'scheduled']  # <-- ADICIONEI 'scheduled'
        and c.get('tipo') == 'funil'
    ]
    
    if not campanhas_ativas:
        print("⚠️ Nenhuma campanha ativa encontrada!")
        return
    
    for campanha in campanhas_ativas:
        if cliente_data.get('campaign_paused', {}).get(campanha['id'], False):
            print(f"⏸️ Campanha pausada, ignorando...")
            continue
        
        contatos_normalizados = [normalizar_numero(c) for c in campanha.get('contacts', [])]
        if numero not in contatos_normalizados:
            continue
        
        if 'contatos_estagio' not in campanha:
            campanha['contatos_estagio'] = {}
        if numero not in campanha['contatos_estagio']:
            campanha['contatos_estagio'][numero] = {'etapa_atual': 0, 'saudacao_enviada': False}
        
        if not campanha['contatos_estagio'][numero].get('saudacao_enviada', False):
            print(f"⏭️ Saudação ainda não enviada para {numero}")
            continue
        
        if campanha['contatos_estagio'][numero].get('concluido', False):
            print(f"⏭️ Contato {numero} já concluiu todas as etapas!")
            continue
        
        etapa_atual = campanha['contatos_estagio'][numero].get('etapa_atual', 0)
        funil_id = campanha.get('funil_id')
        funis = cliente_data.get('funis', [])
        funil = next((f for f in funis if f['id'] == funil_id), funis[0] if funis else None)
        
        if not funil:
            continue
        
        etapas = funil.get('etapas', [])
        total_etapas = len(etapas)
        
        if etapa_atual >= len(etapas) - 1:
            campanha['contatos_estagio'][numero]['concluido'] = True
            save_cliente_data(cliente_id, cliente_data)
            print(f"🏁 Contato {numero} já completou todas as etapas!")
            
            todos_concluidos = all(
                campanha['contatos_estagio'].get(c, {}).get('concluido', False) 
                for c in campanha['contacts']
            )
            if todos_concluidos:
                campanha['status'] = 'completed'
                print(f"🏁 Campanha {campanha['name']} concluída!")
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'success',
                    'message': f'Campanha {campanha["name"]} concluída!'
                })
                save_cliente_data(cliente_id, cliente_data)
            return
        
        if any(p in texto_lower for p in palavras_desinteresse):
            print(f"❌ Desinteresse detectado para {numero}")
            mensagem_final = f"{get_saudacao_por_horario()}! Agradecemos seu retorno.\n\nCaso mude de ideia no futuro, estaremos à disposição.\n\nSucesso! 💼"
            send_humanized_message(instance_name, numero, mensagem_final, "Encerramento", current_user=current_user)
            campanha['contatos_estagio'][numero]['concluido'] = True
            save_cliente_data(cliente_id, cliente_data)
            print(f"✅ Conversa encerrada com {numero} (desinteresse)")
            return
        
        if any(p in texto_lower for p in palavras_duvida):
            if etapa_atual == 0:
                print(f"❓ Dúvida detectada para {numero} na primeira etapa")
                mensagem_final = f"{get_saudacao_por_horario()}! Entendo sua dúvida.\n\nGostaria de receber a descrição completa da vaga para analisar com calma?"
                send_humanized_message(instance_name, numero, mensagem_final, "Esclarecimento", current_user=current_user)
                save_cliente_data(cliente_id, cliente_data)
                print(f"📤 Resposta de dúvida enviada para {numero}")
                return
            else:
                print(f"⏭️ Dúvida ignorada - Funil já em andamento para {numero} (etapa {etapa_atual+1})")
                return
        
        if any(p in texto_lower for p in palavras_interesse):
            print(f"✅ Interesse detectado para {numero} - Etapa atual: {etapa_atual+1}/{total_etapas}")
            
            nova_etapa = etapa_atual + 1
            campanha['contatos_estagio'][numero]['etapa_atual'] = nova_etapa
            
            proxima_etapa = etapas[nova_etapa]
            etapa_id = proxima_etapa.get('id')
            delay = proxima_etapa.get('delay_apos_resposta', 10)
            nome_proxima_etapa = proxima_etapa.get('nome', f'Etapa {nova_etapa+1}')
            
            print(f"✅ Avançando para etapa {nova_etapa+1}/{total_etapas} ({nome_proxima_etapa})")
            
            time.sleep(delay)
            
            dados = campanha.get('dados_funil', {})
            mensagem, _ = montar_mensagem_funil_flexivel(etapa_id, dados, funil_id, cliente_id)
            
            if mensagem:
                send_humanized_message(
                    instance_name, 
                    numero, 
                    mensagem, 
                    nome_proxima_etapa,
                    delay_manual=delay,
                    etapa_atual=nova_etapa+1,
                    total_etapas=total_etapas,
                    current_user=current_user
                )
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'success',
                    'message': f'Mensagem "{nome_proxima_etapa}" ({nova_etapa+1}/{total_etapas}) enviada para {numero}'
                })
                save_cliente_data(cliente_id, cliente_data)
                print(f"✅ VAGA enviada para {numero}")
            
            delay_proximo = random.randint(120, 180)
            print(f"⏳ Próxima mensagem (LINK DE CADASTRO) em {delay_proximo}s...")
            
            def enviar_proximo_automatico():
                time.sleep(delay_proximo)
                
                cliente_data_local = load_cliente_data(cliente_id)
                campanha_local = next((c for c in cliente_data_local.get('campaigns', []) if c['id'] == campanha['id']), None)
                if not campanha_local:
                    return
                
                if campanha_local['contatos_estagio'].get(numero, {}).get('concluido', False):
                    print(f"⏭️ Contato {numero} já concluiu, não enviando automaticamente")
                    return
                
                etapa_atual_check = campanha_local['contatos_estagio'].get(numero, {}).get('etapa_atual', 0)
                if etapa_atual_check != nova_etapa:
                    print(f"⏭️ Contato {numero} já avançou, não enviando automaticamente")
                    return
                
                proxima_etapa_idx = nova_etapa + 1
                
                if proxima_etapa_idx < len(etapas):
                    campanha_local['contatos_estagio'][numero]['etapa_atual'] = proxima_etapa_idx
                    
                    etapa_cadastro = etapas[proxima_etapa_idx]
                    etapa_id_cadastro = etapa_cadastro.get('id')
                    delay_cadastro = etapa_cadastro.get('delay_apos_resposta', 10)
                    nome_cadastro = etapa_cadastro.get('nome', f'Etapa {proxima_etapa_idx+1}')
                    
                    print(f"📤 Enviando automaticamente: {nome_cadastro}")
                    time.sleep(delay_cadastro)
                    
                    mensagem_cadastro, _ = montar_mensagem_funil_flexivel(etapa_id_cadastro, dados, funil_id, cliente_id)
                    
                    if mensagem_cadastro:
                        send_humanized_message(
                            instance_name, 
                            numero, 
                            mensagem_cadastro, 
                            nome_cadastro,
                            delay_manual=delay_cadastro,
                            etapa_atual=proxima_etapa_idx+1,
                            total_etapas=total_etapas,
                            current_user=current_user
                        )
                        cliente_data_local['logs'].append({
                            'time': datetime.now().isoformat(),
                            'type': 'success',
                            'message': f'Mensagem "{nome_cadastro}" ({proxima_etapa_idx+1}/{total_etapas}) enviada automaticamente para {numero}'
                        })
                        save_cliente_data(cliente_id, cliente_data_local)
                        print(f"✅ LINK DE CADASTRO enviado para {numero}")
                    
                    delay_verificacao = random.randint(120, 180)
                    print(f"⏳ Próxima mensagem (VERIFICAÇÃO) em {delay_verificacao}s...")
                    
                    def enviar_verificacao():
                        time.sleep(delay_verificacao)
                        
                        cliente_data_verif = load_cliente_data(cliente_id)
                        campanha_verif = next((c for c in cliente_data_verif.get('campaigns', []) if c['id'] == campanha['id']), None)
                        if not campanha_verif:
                            return
                        
                        if campanha_verif['contatos_estagio'].get(numero, {}).get('concluido', False):
                            print(f"⏭️ Contato {numero} já concluiu, não enviando verificação")
                            return
                        
                        etapa_atual_check2 = campanha_verif['contatos_estagio'].get(numero, {}).get('etapa_atual', 0)
                        if etapa_atual_check2 != proxima_etapa_idx:
                            print(f"⏭️ Contato {numero} já avançou, não enviando verificação")
                            return
                        
                        verificacao_idx = proxima_etapa_idx + 1
                        
                        if verificacao_idx < len(etapas):
                            campanha_verif['contatos_estagio'][numero]['etapa_atual'] = verificacao_idx
                            
                            etapa_verificacao = etapas[verificacao_idx]
                            etapa_id_verificacao = etapa_verificacao.get('id')
                            delay_verif = etapa_verificacao.get('delay_apos_resposta', 10)
                            nome_verificacao = etapa_verificacao.get('nome', f'Etapa {verificacao_idx+1}')
                            
                            print(f"📤 Enviando automaticamente: {nome_verificacao}")
                            time.sleep(delay_verif)
                            
                            mensagem_verificacao, _ = montar_mensagem_funil_flexivel(etapa_id_verificacao, dados, funil_id, cliente_id)
                            
                            if mensagem_verificacao:
                                send_humanized_message(
                                    instance_name, 
                                    numero, 
                                    mensagem_verificacao, 
                                    nome_verificacao,
                                    delay_manual=delay_verif,
                                    etapa_atual=verificacao_idx+1,
                                    total_etapas=total_etapas,
                                    current_user=current_user
                                )
                                cliente_data_verif['logs'].append({
                                    'time': datetime.now().isoformat(),
                                    'type': 'success',
                                    'message': f'Mensagem "{nome_verificacao}" ({verificacao_idx+1}/{total_etapas}) enviada automaticamente para {numero}'
                                })
                                save_cliente_data(cliente_id, cliente_data_verif)
                                print(f"✅ VERIFICAÇÃO enviada para {numero}")
                                
                                campanha_verif['contatos_estagio'][numero]['concluido'] = True
                                save_cliente_data(cliente_id, cliente_data_verif)
                                print(f"🏁 Contato {numero} concluiu todas as etapas!")
                                
                                todos_concluidos = all(
                                    campanha_verif['contatos_estagio'].get(c, {}).get('concluido', False) 
                                    for c in campanha_verif['contacts']
                                )
                                if todos_concluidos:
                                    campanha_verif['status'] = 'completed'
                                    print(f"🏁 Campanha {campanha_verif['name']} concluída!")
                                    cliente_data_verif['logs'].append({
                                        'time': datetime.now().isoformat(),
                                        'type': 'success',
                                        'message': f'Campanha {campanha_verif["name"]} concluída!'
                                    })
                                    save_cliente_data(cliente_id, cliente_data_verif)
                    
                    thread_verificacao = threading.Thread(target=enviar_verificacao)
                    thread_verificacao.daemon = True
                    thread_verificacao.start()
            
            thread_cadastro = threading.Thread(target=enviar_proximo_automatico)
            thread_cadastro.daemon = True
            thread_cadastro.start()
            
            return
        
        print(f"🤔 Neutro detectado para {numero} - Etapa atual: {etapa_atual+1}/{total_etapas}")
        
        if etapa_atual == 0:
            mensagem = f"{get_saudacao_por_horario()}! Gostaria de confirmar: você tem interesse em conhecer mais detalhes sobre a vaga que mencionei? 😊"
            send_humanized_message(instance_name, numero, mensagem, "Confirmação de Interesse", current_user=current_user)
            save_cliente_data(cliente_id, cliente_data)
            print(f"📤 Mensagem de confirmação enviada para {numero}")
            return
        
        mensagem = f"{get_saudacao_por_horario()}! Para dar continuidade ao processo, preciso saber se você tem interesse em receber a próxima etapa. 😊"
        send_humanized_message(instance_name, numero, mensagem, "Confirmação de Continuidade", current_user=current_user)
        save_cliente_data(cliente_id, cliente_data)
        print(f"📤 Mensagem de continuidade enviada para {numero}")
        
        break

# ============================================
# ROTA: VALIDAÇÃO WHATSAPP
# ============================================
@app.route('/api/validate/whatsapp', methods=['POST'])
@token_required
def validate_whatsapp_numbers(current_user):
    try:
        data = request.get_json() or {}
        numbers = data.get('numbers', [])
        instance = data.get('instance', '')
        
        if not numbers:
            return jsonify({'success': False, 'error': 'Lista de números vazia'}), 400
        if not instance:
            return jsonify({'success': False, 'error': 'Selecione uma instância para validar'}), 400
        
        headers = {"apikey": EVO_API_KEY}
        
        # Verifica se a instância existe e está online
        try:
            instance_check_url = f"{EVO_SERVER}/instance/fetchInstances"
            instances_response = requests.get(instance_check_url, headers=headers, timeout=10)
            
            if instances_response.status_code != 200:
                return jsonify({'success': False, 'error': 'Erro ao verificar instâncias'}), 500
            
            instances_data = instances_response.json()
            instance_exists = False
            instance_online = False
            
            for inst in instances_data:
                if inst.get('name') == instance:
                    instance_exists = True
                    if inst.get('connectionStatus') in ['open', 'connected']:
                        instance_online = True
                    break
            
            if not instance_exists:
                return jsonify({'success': False, 'error': f'Instância "{instance}" não encontrada'}), 404
            
            if not instance_online:
                return jsonify({'success': False, 'error': f'Instância "{instance}" está offline. Conecte-a primeiro.'}), 400
                
            print(f"✅ Instância {instance} está online")
                
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {e}")
        
        # Prepara os números para validação
        numeros_para_validar = []
        
        for n in numbers:
            if not n or not str(n).strip():
                continue
            
            limpo = re.sub(r'\D', '', str(n))
            if not limpo:
                continue
            
            if len(limpo) == 13 and limpo.startswith('55'):
                if limpo[4] == '9':
                    formatado = limpo
                else:
                    formatado = limpo[:4] + '9' + limpo[4:]
            elif len(limpo) == 11:
                if limpo[2] == '9':
                    formatado = f"55{limpo}"
                else:
                    formatado = f"55{limpo[:2]}9{limpo[2:]}"
            elif len(limpo) == 10:
                formatado = f"55{limpo[:2]}9{limpo[2:]}"
            elif len(limpo) == 12 and limpo.startswith('55'):
                formatado = limpo[:4] + '9' + limpo[4:]
            elif len(limpo) == 13 and limpo.startswith('55'):
                formatado = limpo
            else:
                formatado = f"55{limpo}"
                if len(formatado) == 12:
                    formatado = formatado[:4] + '9' + formatado[4:]
            
            numeros_para_validar.append(formatado)
            print(f"📱 {n} -> {formatado}")
        
        if not numeros_para_validar:
            return jsonify({'success': False, 'error': 'Nenhum número válido encontrado'}), 400
        
        print(f"🔍 Validando {len(numeros_para_validar)} números na instância {instance}")
        print(f"📋 Números: {numeros_para_validar}")
        
        validated = []
        invalid = []
        total = len(numeros_para_validar)
        
        # ============================================
        # VALIDAÇÃO COM DELAY PARA EVITAR BLOQUEIO
        # ============================================
        for idx, number in enumerate(numeros_para_validar):
            try:
                print(f"⏳ Validando {idx+1}/{total}: {number}...")
                
                url = f"{EVO_SERVER}/chat/whatsappNumbers/{instance}"
                payload = {"numbers": [number]}
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    response_data = response.json()
                    
                    # Processa a resposta
                    exists = False
                    name = ''
                    
                    if isinstance(response_data, list) and len(response_data) > 0:
                        item = response_data[0]
                        exists = item.get('exists', False)
                        name = item.get('name', '')
                    elif isinstance(response_data, dict):
                        if 'data' in response_data and isinstance(response_data['data'], list) and len(response_data['data']) > 0:
                            item = response_data['data'][0]
                            exists = item.get('exists', False)
                            name = item.get('name', '')
                        else:
                            # Tenta pegar diretamente
                            for key, value in response_data.items():
                                if isinstance(value, dict):
                                    exists = value.get('exists', False)
                                    name = value.get('name', '')
                                    break
                    
                    if exists:
                        validated.append({
                            'number': number,
                            'original': number,
                            'formatted': number,
                            'exists': True,
                            'name': name,
                            'status': 'valid'
                        })
                        print(f"  ✅ {number}: WhatsApp encontrado! Nome: {name}")
                    else:
                        invalid.append({
                            'number': number,
                            'original': number,
                            'formatted': number,
                            'exists': False,
                            'status': 'invalid'
                        })
                        print(f"  ❌ {number}: NÃO tem WhatsApp")
                else:
                    print(f"  ⚠️ Erro {response.status_code} ao validar {number}")
                    invalid.append({
                        'number': number,
                        'original': number,
                        'formatted': number,
                        'exists': False,
                        'status': 'error',
                        'error': f'Status {response.status_code}'
                    })
                    
            except Exception as e:
                print(f"  ❌ Exceção ao validar {number}: {e}")
                invalid.append({
                    'number': number,
                    'original': number,
                    'formatted': number,
                    'exists': False,
                    'status': 'error',
                    'error': str(e)
                })
            
            # ============================================
            # DELAY DE 2-3 SEGUNDOS ENTRE CADA VALIDAÇÃO
            # (menos no último)
            # ============================================
            if idx < total - 1:
                delay = random.randint(2, 3)
                print(f"⏳ Aguardando {delay}s para evitar bloqueio...")
                time.sleep(delay)
        
        total_valid = len(validated)
        total_invalid = len(invalid)
        
        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'valid': total_valid,
                'invalid': total_invalid,
                'validated': validated,
                'invalid_list': invalid,
                'valid_numbers': [v['formatted'] for v in validated],
                'valid_original': [v['original'] for v in validated],
                'invalid_numbers': [i['original'] for i in invalid],
                'summary': f"{total_valid} números válidos de {total} ({round(total_valid/total*100, 1) if total > 0 else 0}%)"
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Erro na validação: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: INSTÂNCIAS
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
    except Exception as e:
        print(f"❌ Erro ao buscar instâncias: {e}")
        return []

@app.route('/api/instances', methods=['GET'])
@token_required
def get_instances(current_user):
    try:
        evo_data = get_evolution_instances()
        return jsonify({'success': True, 'data': evo_data, 'count': len(evo_data)}), 200
    except Exception as e:
        print(f"❌ Erro em get_instances: {e}")
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
        
        cliente_data = get_client_data(current_user)
        
        if not verificar_limite_instancias(current_user, cliente_data):
            plano = get_plano_usuario(current_user)
            return jsonify({
                'success': False,
                'error': f'Limite do plano {plano["nome"]} atingido. Máximo: {plano["max_instancias"]} instâncias.'
            }), 403
        
        payload = {
            'instanceName': instance_name,
            'token': f'token_{instance_name}_{int(datetime.now().timestamp())}',
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        }
        
        url = f"{EVO_SERVER}/instance/create"
        headers = {'Content-Type': 'application/json', 'apikey': EVO_API_KEY}
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code not in [200, 201]:
            return jsonify({'success': False, 'error': response.text}), response.status_code
        
        proxy_configurado = False
        if proxy.get('host') and proxy.get('port'):
            proxy_url = f"{EVO_SERVER}/proxy/set/{instance_name}"
            
            proxy_payload = {
                'enabled': True,
                'host': proxy['host'],
                'port': str(proxy['port']),
                'protocol': proxy.get('protocol', 'http')
            }
            
            if proxy.get('username'):
                proxy_payload['username'] = proxy['username']
            if proxy.get('password'):
                proxy_payload['password'] = proxy['password']
            
            print(f"🔧 Configurando proxy: {proxy_payload}")
            
            try:
                proxy_response = requests.post(proxy_url, json=proxy_payload, headers=headers, timeout=30)
                
                if proxy_response.status_code in [200, 201, 204]:
                    proxy_configurado = True
                    print(f"✅ Proxy configurado com sucesso!")
                else:
                    print(f"⚠️ Falha ao configurar proxy: {proxy_response.text}")
            except Exception as e:
                print(f"❌ Erro ao configurar proxy: {e}")
        
        instance_data = {
            'name': instance_name,
            'user_id': current_user['id'],
            'created_at': datetime.now().isoformat(),
            'proxy_configured': proxy_configurado,
            'proxy': proxy if (proxy.get('host') and proxy.get('port')) else None
        }
        cliente_data['instances'].append(instance_data)
        save_client_data(current_user)
        
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'success',
            'message': f'Instância {instance_name} criada por {current_user["email"]}'
        })
        save_client_data(current_user)
        
        return jsonify({'success': True, 'data': response.json()}), 201
        
    except Exception as e:
        print(f"❌ Erro: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/instances/<instance_name>', methods=['DELETE'])
@token_required
def delete_instance(current_user, instance_name):
    try:
        cliente_data = get_client_data(current_user)
        cliente_data['instances'] = [i for i in cliente_data.get('instances', []) if i.get('name') != instance_name or i.get('user_id') == current_user['id'] or current_user.get('role') == 'admin']
        url = f"{EVO_SERVER}/instance/delete/{instance_name}"
        headers = {"apikey": EVO_API_KEY}
        response = requests.delete(url, headers=headers, timeout=30)
        if response.status_code in [200, 204]:
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'Instância {instance_name} deletada por {current_user["email"]}'
            })
            save_client_data(current_user)
            return jsonify({'success': True, 'message': 'Instância deletada'}), 200
        return jsonify({'success': False, 'error': response.text}), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/instances/<instance_name>/force-qr', methods=['GET'])
@token_required
def force_qr(current_user, instance_name):
    try:
        headers = {"apikey": EVO_API_KEY}
        
        logout_url = f"{EVO_SERVER}/instance/logout/{instance_name}"
        try:
            requests.delete(logout_url, headers=headers, timeout=5)
            print(f"🔄 Logout realizado para {instance_name}")
        except:
            pass
        
        time.sleep(2)
        
        connect_url = f"{EVO_SERVER}/instance/connect/{instance_name}"
        response = requests.get(connect_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            qrcode = data.get('qrcode') or data.get('base64')
            
            if qrcode:
                print(f"✅ QR Code gerado para {instance_name}")
                return jsonify({
                    'success': True,
                    'qrcode': qrcode,
                    'data': data,
                    'message': 'QR Code gerado com sucesso! Escaneie com o WhatsApp.'
                }), 200
            else:
                qr_url = f"{EVO_SERVER}/instance/fetchQR/{instance_name}"
                qr_response = requests.get(qr_url, headers=headers, timeout=10)
                
                if qr_response.status_code == 200:
                    qr_data = qr_response.json()
                    qrcode = qr_data.get('base64') or qr_data.get('qrcode')
                    if qrcode:
                        return jsonify({
                            'success': True,
                            'qrcode': qrcode,
                            'data': qr_data,
                            'message': 'QR Code recuperado com sucesso!'
                        }), 200
                
                return jsonify({
                    'success': False,
                    'error': 'QR Code não gerado. A instância pode estar com problemas.',
                    'data': data
                }), 400
        
        return jsonify({'success': False, 'error': response.text}), response.status_code
        
    except Exception as e:
        print(f"❌ ERRO: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: TEMPLATES
# ============================================
@app.route('/api/templates', methods=['GET'])
@token_required
def get_templates(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_templates = cliente_data.get('templates', [])
    else:
        user_templates = [t for t in cliente_data.get('templates', []) if t.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_templates}), 200

@app.route('/api/templates', methods=['POST'])
@token_required
def create_template(current_user):
    try:
        data = request.get_json()
        name = data.get('name')
        message = data.get('message')
        variables = data.get('variables', [])
        if not name or not message:
            return jsonify({'success': False, 'error': 'Nome e mensagem são obrigatórios'}), 400
        
        cliente_data = get_client_data(current_user)
        template = {
            'id': len(cliente_data.get('templates', [])) + 1,
            'user_id': current_user['id'],
            'name': name,
            'message': message,
            'variables': variables,
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat()
        }
        cliente_data['templates'].append(template)
        save_client_data(current_user)
        return jsonify({'success': True, 'data': template}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/templates/<int:template_id>', methods=['DELETE'])
@token_required
def delete_template(current_user, template_id):
    try:
        cliente_data = get_client_data(current_user)
        template = next((t for t in cliente_data.get('templates', []) if t['id'] == template_id), None)
        if not template:
            return jsonify({'success': False, 'error': 'Template não encontrado'}), 404
        if template.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        cliente_data['templates'].remove(template)
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Template excluído'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: FUNIS
# ============================================
@app.route('/api/funis', methods=['GET'])
@token_required
def get_funis(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_funis = cliente_data.get('funis', [])
    else:
        user_funis = [f for f in cliente_data.get('funis', []) if f.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_funis, 'count': len(user_funis)}), 200

@app.route('/api/funis', methods=['POST'])
@token_required
def create_funil(current_user):
    try:
        data = request.get_json()
        nome = data.get('nome')
        descricao = data.get('descricao', '')
        etapas = data.get('etapas', [])
        if not nome or not etapas:
            return jsonify({'success': False, 'error': 'Nome e etapas são obrigatórios'}), 400
        
        cliente_data = get_client_data(current_user)
        funil = {
            'id': len(cliente_data.get('funis', [])) + 1,
            'user_id': current_user['id'],
            'nome': nome,
            'descricao': descricao,
            'etapas': etapas,
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        cliente_data['funis'].append(funil)
        save_client_data(current_user)
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'success',
            'message': f'Funil "{nome}" criado por {current_user["email"]}'
        })
        save_client_data(current_user)
        return jsonify({'success': True, 'data': funil}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/funis/<int:funil_id>', methods=['PUT'])
@token_required
def update_funil(current_user, funil_id):
    try:
        data = request.get_json()
        cliente_data = get_client_data(current_user)
        funil = next((f for f in cliente_data.get('funis', []) if f['id'] == funil_id), None)
        if not funil:
            return jsonify({'success': False, 'error': 'Funil não encontrado'}), 404
        if funil.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        if 'nome' in data:
            funil['nome'] = data['nome']
        if 'descricao' in data:
            funil['descricao'] = data['descricao']
        if 'etapas' in data:
            funil['etapas'] = data['etapas']
        funil['updated_at'] = datetime.now().isoformat()
        save_client_data(current_user)
        return jsonify({'success': True, 'data': funil}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/funis/<int:funil_id>', methods=['DELETE'])
@token_required
def delete_funil(current_user, funil_id):
    try:
        cliente_data = get_client_data(current_user)
        funil = next((f for f in cliente_data.get('funis', []) if f['id'] == funil_id), None)
        if not funil:
            return jsonify({'success': False, 'error': 'Funil não encontrado'}), 404
        if funil.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        cliente_data['funis'].remove(funil)
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Funil deletado'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/funis/<int:funil_id>/reorder', methods=['POST'])
@token_required
def reorder_funil(current_user, funil_id):
    try:
        data = request.get_json()
        nova_ordem = data.get('ordem', [])
        cliente_data = get_client_data(current_user)
        funil = next((f for f in cliente_data.get('funis', []) if f['id'] == funil_id), None)
        if not funil:
            return jsonify({'success': False, 'error': 'Funil não encontrado'}), 404
        if funil.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        etapas_atuais = funil['etapas']
        etapas_ordenadas = []
        for etapa_id in nova_ordem:
            for etapa in etapas_atuais:
                if etapa.get('id') == etapa_id:
                    etapas_ordenadas.append(etapa)
                    break
        funil['etapas'] = etapas_ordenadas
        funil['updated_at'] = datetime.now().isoformat()
        save_client_data(current_user)
        return jsonify({
            'success': True,
            'data': funil,
            'message': 'Ordem atualizada com sucesso'
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: CAMPANHAS
# ============================================
@app.route('/api/campaigns', methods=['GET'])
@token_required
def get_campaigns(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_campaigns = cliente_data.get('campaigns', [])
    else:
        user_campaigns = [c for c in cliente_data.get('campaigns', []) if c.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_campaigns, 'count': len(user_campaigns)}), 200

@app.route('/api/campaigns/<int:campaign_id>', methods=['DELETE'])
@token_required
def delete_campaign(current_user, campaign_id):
    try:
        cliente_data = get_client_data(current_user)
        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
        if not campaign:
            return jsonify({'success': False, 'error': 'Campanha não encontrada'}), 404
        if campaign.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        cliente_data['campaigns'].remove(campaign)
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Campanha excluída'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/campaigns/cleanup', methods=['POST'])
@token_required
def cleanup_campaigns(current_user):
    try:
        data = request.get_json()
        days = data.get('days', 7)
        cutoff = datetime.now() - timedelta(days=days)
        
        cliente_data = get_client_data(current_user)
        to_delete = []
        for c in cliente_data.get('campaigns', []):
            if current_user.get('role') != 'admin' and c.get('user_id') != current_user['id']:
                continue
            if c.get('status') == 'completed':
                created_at = datetime.fromisoformat(c.get('created_at'))
                if created_at < cutoff:
                    to_delete.append(c)
        for c in to_delete:
            cliente_data['campaigns'].remove(c)
        save_client_data(current_user)
        return jsonify({
            'success': True,
            'message': f'{len(to_delete)} campanhas concluídas com mais de {days} dias foram removidas.'
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/campaigns', methods=['POST'])
@token_required
def create_campaign(current_user):
    try:
        data = request.get_json()
        tipo = data.get('tipo', 'personalizada')
        scheduled_at = data.get('scheduledAt')
        funil_id = data.get('funil_id')
        instances = data.get('instances', [])
        
        cliente_data = get_client_data(current_user)
        
        if not verificar_limite_campanhas(current_user, cliente_data):
            plano = get_plano_usuario(current_user)
            return jsonify({
                'success': False,
                'error': f'Limite do plano {plano["nome"]} atingido. Máximo: {plano["max_campanhas_simultaneas"]} campanhas simultâneas.'
            }), 403
        
        available_instances = get_evolution_instances()
        instance_names = [inst.get('name') or inst.get('instanceName') for inst in available_instances if isinstance(available_instances, list)]
        
        contatos = data.get('contacts', [])
        contatos_normalizados = [normalizar_numero(c) for c in contatos if normalizar_numero(c)]
        
        plano = get_plano_usuario(current_user)
        if len(contatos_normalizados) > plano['max_contatos_por_campanha']:
            return jsonify({
                'success': False,
                'error': f'Limite do plano {plano["nome"]}. Máximo: {plano["max_contatos_por_campanha"]} contatos por campanha.'
            }), 403
        
        message = data.get('message', '')
        dados_funil = data.get('dados_funil', {})
        main_instance = instances[0] if instances and len(instances) > 0 else data.get('instance', '')
        
        instance_online = False
        try:
            headers = {"apikey": EVO_API_KEY}
            check_url = f"{EVO_SERVER}/instance/fetchInstances"
            check_response = requests.get(check_url, headers=headers, timeout=5)
            if check_response.status_code == 200:
                instances_list = check_response.json()
                for inst in instances_list:
                    if inst.get('name') == main_instance:
                        status = inst.get('connectionStatus')
                        owner = inst.get('ownerJid')
                        if status in ['open', 'connected'] and owner:
                            instance_online = True
                            print(f"✅ Instância {main_instance} está ONLINE")
                        else:
                            print(f"⚠️ Instância {main_instance} está com status: {status}")
                        break
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {e}")
        
        if not instance_online and not scheduled_at:
            print(f"⚠️ AVISO: Instância {main_instance} não está online! A campanha pode falhar.")
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'warning',
                'message': f'Campanha criada com instância {main_instance} OFFLINE - Pode falhar'
            })
            save_client_data(current_user)
        
        campaign = {
            'id': len(cliente_data.get('campaigns', [])) + 1,
            'user_id': current_user['id'],
            'name': data.get('name', f'Campanha {len(cliente_data.get("campaigns", [])) + 1}'),
            'tipo': tipo,
            'contacts': contatos_normalizados,
            'instance': main_instance,
            'instances': instances,
            'available_instances': instance_names,
            'status': 'scheduled' if scheduled_at else 'processing',
            'total': len(contatos_normalizados),
            'sent': 0,
            'failed': 0,
            'scheduled_at': scheduled_at,
            'funil_id': funil_id,
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        if tipo == 'funil':
            campaign['dados_funil'] = dados_funil
            campaign['funil_ativa'] = True
            campaign['contatos_estagio'] = {}
        else:
            campaign['mensagem'] = message
            campaign['media'] = data.get('media', {})
            campaign['humanized_config'] = {
                'typing_delay': data.get('typingDelay', 3),
                'typing_speed': data.get('typingSpeed', 50),
                'simulate_typing': data.get('simulateTyping', True),
                'strategic_pause': data.get('strategicPause', True),
                'delay_min': data.get('delayMin', 5),
                'delay_max': data.get('delayMax', 15)
            }
        
        if not campaign['instance'] and not instances:
            return jsonify({'success': False, 'error': 'Selecione pelo menos uma instância para enviar'}), 400
        if len(campaign['contacts']) == 0:
            return jsonify({'success': False, 'error': 'Nenhum contato adicionado'}), 400
        
        cliente_data['campaigns'].append(campaign)
        save_client_data(current_user)
        
        if scheduled_at:
            cliente_data['scheduled_messages'].append({
                'campaign_id': campaign['id'],
                'instanceName': main_instance,
                'instances': instances,
                'number': None,
                'scheduledAt': scheduled_at,
                'status': 'pending',
                'tipo': tipo,
                'message': message,
                'dados_funil': dados_funil if tipo == 'funil' else None,
                'media': data.get('media', {}) if tipo != 'funil' else None,
                'humanized_config': campaign.get('humanized_config', {}),
                'funil_id': funil_id
            })
            save_client_data(current_user)
            send_notification(current_user, f"Campanha {campaign['name']} agendada para {scheduled_at}", 'info')
            return jsonify({'success': True, 'data': campaign, 'scheduled': True}), 201
        
        thread = threading.Thread(target=process_campaign, args=(campaign['id'], current_user))
        thread.daemon = True
        thread.start()
        
        return jsonify({'success': True, 'data': campaign}), 201
    except Exception as e:
        print(f"❌ Erro ao criar campanha: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# PROCESSAR CAMPANHA
# ============================================
def process_campaign(campaign_id, current_user):
    try:
        cliente_data = get_client_data(current_user)
        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
        
        if not campaign:
            print(f"❌ Campanha {campaign_id} não encontrada no cliente {current_user.get('cliente_id', 'default')}!")
            return
        
        print(f"\n{'='*60}")
        print(f"🚀 INICIANDO CAMPANHA: {campaign['name']}")
        print(f"{'='*60}")
        print(f"📱 Instância principal: {campaign.get('instance')}")
        print(f"📊 Tipo: {campaign.get('tipo')}")
        print(f"📊 Total contatos: {len(campaign.get('contacts', []))}")
        print(f"📊 Status: {campaign.get('status')}")
        print(f"{'='*60}\n")
        
        instance = campaign.get('instance')
        instances = campaign.get('instances', [])
        tipo = campaign.get('tipo')
        funil_id = campaign.get('funil_id')
        
        try:
            headers = {"apikey": EVO_API_KEY}
            check_url = f"{EVO_SERVER}/instance/fetchInstances"
            check_response = requests.get(check_url, headers=headers, timeout=5)
            
            if check_response.status_code == 200:
                instances_list = check_response.json()
                inst = next((i for i in instances_list if i.get('name') == instance), None)
                
                if inst:
                    status = inst.get('connectionStatus')
                    owner = inst.get('ownerJid')
                    print(f"📊 Status da instância: {status}")
                    print(f"📊 Owner: {owner}")
                else:
                    print(f"⚠️ Instância {instance} não encontrada na Evolution API! Tentando enviar mesmo assim...")
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {e} - Continuando com a campanha...")
        
        try:
            send_notification(current_user, f"Campanha {campaign['name']} iniciada!", 'info')
        except:
            pass
        
        if instances and len(instances) > 1:
            print(f"📊 Distribuindo {len(campaign['contacts'])} contatos entre {len(instances)} instâncias")
            contacts = campaign['contacts']
            contacts_per_instance = len(contacts) // len(instances)
            remainder = len(contacts) % len(instances)
            start_idx = 0
            for i, inst in enumerate(instances):
                count = contacts_per_instance + (1 if i < remainder else 0)
                end_idx = start_idx + count
                instance_contacts = contacts[start_idx:end_idx]
                sub_campaign = campaign.copy()
                sub_campaign['id'] = f"{campaign['id']}_{i}"
                sub_campaign['instance'] = inst
                sub_campaign['contacts'] = instance_contacts
                sub_campaign['sent'] = 0
                sub_campaign['failed'] = 0
                sub_campaign['status'] = 'processing'
                sub_campaign['contatos_estagio'] = {}
                
                cliente_data['campaigns'].append(sub_campaign)
                save_client_data(current_user)
                
                print(f"  📱 Instância {inst}: {len(instance_contacts)} contatos")
                thread = threading.Thread(target=process_single_instance, args=(sub_campaign, current_user))
                thread.daemon = True
                thread.start()
                start_idx = end_idx
            print(f"✅ Campanha dividida em {len(instances)} partes!")
            return
        
        process_single_instance(campaign, current_user)
        
    except Exception as e:
        print(f"❌ Erro ao processar campanha: {e}")
        import traceback
        traceback.print_exc()

def process_single_instance(campaign, current_user):
    instance = campaign.get('instance')
    tipo = campaign.get('tipo')
    funil_id = campaign.get('funil_id')
    
    print(f"📤 Processando instância única: {instance}")
    print(f"📊 Tipo: {tipo}")
    print(f"📊 Contatos: {len(campaign.get('contacts', []))}")
    
    if tipo == 'funil':
        process_funil_campaign(campaign, instance, funil_id, current_user)
    else:
        process_personalized_campaign(campaign, instance, current_user)

def process_funil_campaign(campaign, instance, funil_id, current_user):
    cliente_data = get_client_data(current_user)
    dados = campaign.get('dados_funil', {})
    funis = cliente_data.get('funis', [])
    funil = next((f for f in funis if f['id'] == funil_id), funis[0] if funis else None)
    
    if not funil:
        campaign['status'] = 'failed'
        print(f"❌ Funil {funil_id} não encontrado!")
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'error',
            'message': f'Campanha {campaign["name"]} falhou: Funil {funil_id} não encontrado'
        })
        save_client_data(current_user)
        return
    
    etapas = funil.get('etapas', [])
    total_etapas = len(etapas)
    
    print(f"📊 Funil: {funil['nome']}")
    print(f"📊 Total etapas: {total_etapas}")
    print(f"📊 Total contatos: {len(campaign.get('contacts', []))}")
    
    for contact in campaign.get('contacts', []):
        if cliente_data.get('campaign_paused', {}).get(campaign['id'], False):
            print(f"⏸️ Campanha pausada no contato {contact}")
            campaign['status'] = 'paused'
            save_client_data(current_user)
            try:
                send_notification(current_user, f"Campanha {campaign['name']} pausada", 'warning')
            except Exception:
                pass
            return
        
        try:
            if 'contatos_estagio' not in campaign:
                campaign['contatos_estagio'] = {}
            if contact not in campaign['contatos_estagio']:
                campaign['contatos_estagio'][contact] = {'etapa_atual': 0, 'saudacao_enviada': False}
                
            if campaign['contatos_estagio'][contact].get('saudacao_enviada', False):
                print(f"⏭️ Saudação já enviada para {contact}")
                continue
            
            primeira_etapa = etapas[0] if etapas else None
            if not primeira_etapa:
                continue
            
            etapa_id = primeira_etapa.get('id')
            cliente_id = current_user.get('cliente_id', 'default')
            mensagem, template_data = montar_mensagem_funil_flexivel(etapa_id, dados, funil_id, cliente_id)
            if not mensagem:
                continue
            
            final_message = process_spintax_avancado(mensagem)
            print(f"📤 Enviando saudação para {contact}")
            
            success, _ = send_humanized_message(
                instance, 
                contact, 
                final_message, 
                primeira_etapa.get('nome', 'Saudação'),
                etapa_atual=1,
                total_etapas=total_etapas,
                current_user=current_user
            )
            
            if success:
                campaign['contatos_estagio'][contact]['saudacao_enviada'] = True
                campaign['contatos_estagio'][contact]['etapa_atual'] = 0
                campaign['sent'] = campaign.get('sent', 0) + 1
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'success',
                    'message': f'Saudação enviada para {contact} via {instance}'
                })
            else:
                campaign['failed'] = campaign.get('failed', 0) + 1
                cliente_data['logs'].append({
                    'time': datetime.now().isoformat(),
                    'type': 'error',
                    'message': f'Falha ao enviar saudação para {contact} via {instance}'
                })
            
            save_client_data(current_user)
            
            delay_entre_contatos = random.randint(10, 20)
            print(f"⏳ Aguardando {delay_entre_contatos}s para o próximo contato...")
            time.sleep(delay_entre_contatos)
            
        except Exception as e:
            print(f"❌ Erro ao processar contato {contact}: {e}")
            campaign['failed'] = campaign.get('failed', 0) + 1
            save_client_data(current_user)
            
    campaign['status'] = 'processing'
    campaign['updated_at'] = datetime.now().isoformat()
    save_client_data(current_user)
    print(f"✅ Envio inicial da campanha {campaign['name']} concluído. Aguardando respostas dos leads.")

def process_personalized_campaign(campaign, instance, current_user):
    cliente_data = get_client_data(current_user)
    config = campaign.get('humanized_config', {})
    mensagem = campaign.get('mensagem', '')
    media = campaign.get('media', {})
    
    print(f"\n{'='*60}")
    print(f"📊 INICIANDO CAMPANHA PERSONALIZADA")
    print(f"{'='*60}")
    print(f"📱 Instância: {instance}")
    print(f"📊 Total contatos: {len(campaign['contacts'])}")
    print(f"💬 Mensagem: {mensagem[:100]}{'...' if len(mensagem) > 100 else ''}")
    print(f"{'='*60}\n")
    
    for contact in campaign['contacts']:
        if cliente_data.get('campaign_paused', {}).get(campaign['id'], False):
            print(f"⏸️ Campanha pausada no contato {contact}")
            campaign['status'] = 'paused'
            save_client_data(current_user)
            try:
                send_notification(current_user, f"Campanha {campaign['name']} pausada", 'warning')
            except:
                pass
            return
        
        try:
            print(f"\n--- Processando contato: {contact} ---")
            
            final_message = process_spintax_avancado(mensagem)
            media_data = None
            media_type = 'image'
            
            if media:
                if isinstance(media, dict):
                    media_data = media.get('file') or media.get('data') or media.get('media')
                elif isinstance(media, str):
                    media_data = media
                
                if media_data:
                    if isinstance(media_data, str):
                        if 'data:video' in media_data:
                            media_type = 'video'
                        elif 'data:image' in media_data:
                            media_type = 'image'
                        elif 'data:application/pdf' in media_data:
                            media_type = 'document'
            
            if media_data:
                print(f"📤 Enviando {media_type} com legenda para {contact}")
                if config.get('simulate_typing', True):
                    typing_time = min(len(final_message) / config.get('typing_speed', 50), 5)
                    time.sleep(typing_time)
                success, result = send_media_message(instance, contact, media_data, final_message, media_type, current_user)
                if success:
                    campaign['sent'] += 1
                    print(f"✅ {media_type} enviado para {contact}")
                else:
                    campaign['failed'] += 1
                    erro_msg = f"❌ Falha ao enviar {media_type} para {contact}: {result}"
                    print(erro_msg)
                    cliente_data['logs'].append({
                        'time': datetime.now().isoformat(),
                        'type': 'error',
                        'message': f'Campanha {campaign["name"]}: {erro_msg}'
                    })
            else:
                print(f"📤 Enviando texto para {contact}")
                if config.get('simulate_typing', True):
                    typing_time = min(len(final_message) / config.get('typing_speed', 50), 5)
                    time.sleep(typing_time)
                success, result = send_humanized_message(instance, contact, final_message, 'Personalizada', current_user=current_user)
                if success:
                    campaign['sent'] += 1
                    print(f"✅ Mensagem enviada para {contact}")
                else:
                    campaign['failed'] += 1
                    erro_msg = f"❌ Falha ao enviar para {contact}: {result}"
                    print(erro_msg)
                    cliente_data['logs'].append({
                        'time': datetime.now().isoformat(),
                        'type': 'error',
                        'message': f'Campanha {campaign["name"]}: {erro_msg}'
                    })
            
            save_client_data(current_user)
            if campaign['contacts'].index(contact) < len(campaign['contacts']) - 1:
                delay = random.randint(config.get('delay_min', 5), config.get('delay_max', 15))
                print(f"⏳ Aguardando {delay}s para próximo contato...")
                time.sleep(delay)
        except Exception as e:
            campaign['failed'] += 1
            erro_msg = f"❌ Erro ao enviar para {contact}: {str(e)}"
            print(erro_msg)
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'error',
                'message': f'Campanha {campaign["name"]}: {erro_msg}'
            })
            import traceback
            traceback.print_exc()
            save_client_data(current_user)
    
    campaign['status'] = 'completed'
    save_client_data(current_user)
    print(f"\n🏁 Campanha {campaign['name']} concluída!")
    try:
        send_notification(current_user, f"Campanha {campaign['name']} concluída!", 'success')
    except:
        pass

# ============================================
# ROTA: PAUSAR/RETOMAR/FINALIZAR CAMPANHA
# ============================================
@app.route('/api/campaigns/<int:campaign_id>/pause', methods=['POST'])
@token_required
def pause_campaign(current_user, campaign_id):
    try:
        cliente_data = get_client_data(current_user)
        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
        
        if not campaign:
            return jsonify({'success': False, 'error': 'Campanha não encontrada'}), 404
        
        if campaign.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        
        if 'campaign_paused' not in cliente_data:
            cliente_data['campaign_paused'] = {}
        cliente_data['campaign_paused'][campaign_id] = True
        campaign['status'] = 'paused'
        
        save_client_data(current_user)
        send_notification(current_user, f"Campanha {campaign['name']} pausada", 'warning')
        
        return jsonify({'success': True, 'message': 'Campanha pausada'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/campaigns/<int:campaign_id>/resume', methods=['POST'])
@token_required
def resume_campaign(current_user, campaign_id):
    try:
        cliente_data = get_client_data(current_user)
        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
        
        if not campaign:
            return jsonify({'success': False, 'error': 'Campanha não encontrada'}), 404
        
        if campaign.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        
        if 'campaign_paused' not in cliente_data:
            cliente_data['campaign_paused'] = {}
        cliente_data['campaign_paused'][campaign_id] = False
        campaign['status'] = 'processing'
        
        save_client_data(current_user)
        send_notification(current_user, f"Campanha {campaign['name']} retomada", 'success')
        
        return jsonify({'success': True, 'message': 'Campanha retomada'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/campaigns/<int:campaign_id>/complete', methods=['POST'])
@token_required
def complete_campaign(current_user, campaign_id):
    try:
        cliente_data = get_client_data(current_user)
        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
        
        if not campaign:
            return jsonify({'success': False, 'error': 'Campanha não encontrada'}), 404
        
        if campaign.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        
        campaign['status'] = 'completed'
        for contact in campaign.get('contacts', []):
            if contact in campaign.get('contatos_estagio', {}):
                campaign['contatos_estagio'][contact]['concluido'] = True
        
        save_client_data(current_user)
        send_notification(current_user, f"Campanha {campaign['name']} finalizada", 'success')
        
        return jsonify({'success': True, 'message': 'Campanha finalizada'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: QUICK REPLIES
# ============================================
@app.route('/api/quick-replies', methods=['GET'])
@token_required
def get_quick_replies(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_replies = cliente_data.get('quick_replies', [])
    else:
        user_replies = [r for r in cliente_data.get('quick_replies', []) if r.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_replies}), 200

@app.route('/api/quick-replies', methods=['POST'])
@token_required
def create_quick_reply(current_user):
    try:
        data = request.get_json()
        title = data.get('title')
        message = data.get('message')
        if not title or not message:
            return jsonify({'success': False, 'error': 'Título e mensagem são obrigatórios'}), 400
        
        cliente_data = get_client_data(current_user)
        reply = {
            'id': len(cliente_data.get('quick_replies', [])) + 1,
            'user_id': current_user['id'],
            'title': title,
            'message': message,
            'created_by': current_user['email'],
            'created_at': datetime.now().isoformat()
        }
        cliente_data['quick_replies'].append(reply)
        save_client_data(current_user)
        return jsonify({'success': True, 'data': reply}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/quick-replies/<int:reply_id>', methods=['DELETE'])
@token_required
def delete_quick_reply(current_user, reply_id):
    try:
        cliente_data = get_client_data(current_user)
        reply = next((r for r in cliente_data.get('quick_replies', []) if r['id'] == reply_id), None)
        if not reply:
            return jsonify({'success': False, 'error': 'Resposta não encontrada'}), 404
        if reply.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        cliente_data['quick_replies'].remove(reply)
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Resposta excluída'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: LOGS
# ============================================
@app.route('/api/logs', methods=['GET'])
@token_required
def get_logs(current_user):
    log_type = request.args.get('type')
    cliente_data = get_client_data(current_user)
    
    if current_user.get('role') == 'admin':
        filtered = cliente_data.get('logs', []).copy()
    else:
        filtered = [l for l in cliente_data.get('logs', []) if l.get('user_id') == current_user['id'] or l.get('user_id') is None]
    
    if log_type and log_type != 'all':
        filtered = [l for l in filtered if l.get('type') == log_type]
    filtered.sort(key=lambda x: x.get('time', ''), reverse=True)
    return jsonify({'success': True, 'data': filtered[:100]}), 200

# ============================================
# ROTA: CONTATOS
# ============================================
@app.route('/api/contacts', methods=['GET'])
@token_required
def get_contacts(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_contacts = cliente_data.get('contacts', [])
    else:
        user_contacts = [c for c in cliente_data.get('contacts', []) if c.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_contacts, 'count': len(user_contacts)}), 200

@app.route('/api/contacts', methods=['POST'])
@token_required
def import_contacts(current_user):
    try:
        data = request.get_json()
        numbers = data.get('numbers', [])
        cliente_data = get_client_data(current_user)
        
        for number in numbers:
            cleaned = normalizar_numero(number)
            if re.match(r'^\+?[0-9]{10,15}$', cleaned):
                if not any(c['number'] == cleaned for c in cliente_data.get('contacts', [])):
                    cliente_data['contacts'].append({
                        'id': len(cliente_data.get('contacts', [])) + 1,
                        'user_id': current_user['id'],
                        'number': cleaned,
                        'name': data.get('name', f'Contato {len(cliente_data.get("contacts", [])) + 1}'),
                        'validated': True,
                        'messages_count': 0,
                        'created_at': datetime.now().isoformat()
                    })
        save_client_data(current_user)
        return jsonify({'success': True, 'message': f'{len(numbers)} contatos importados'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: WARMUP
# ============================================
@app.route('/api/warmup', methods=['GET'])
@token_required
def get_warmups(current_user):
    cliente_data = get_client_data(current_user)
    if current_user.get('role') == 'admin':
        user_warmups = cliente_data.get('warmups', [])
    else:
        user_warmups = [w for w in cliente_data.get('warmups', []) if w.get('user_id') == current_user['id']]
    return jsonify({'success': True, 'data': user_warmups, 'count': len(user_warmups)}), 200

@app.route('/api/warmup', methods=['POST'])
@token_required
def create_warmup(current_user):
    try:
        data = request.get_json()
        cliente_data = get_client_data(current_user)
        warmup = {
            'id': len(cliente_data.get('warmups', [])) + 1,
            'user_id': current_user['id'],
            'name': data.get('name', f'Aquecimento {len(cliente_data.get("warmups", [])) + 1}'),
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
        cliente_data['warmups'].append(warmup)
        save_client_data(current_user)
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'success',
            'message': f'Warmup "{warmup["name"]}" criado por {current_user["email"]}'
        })
        save_client_data(current_user)
        return jsonify({'success': True, 'data': warmup}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/warmup/<int:warmup_id>/toggle', methods=['POST'])
@token_required
def toggle_warmup(current_user, warmup_id):
    cliente_data = get_client_data(current_user)
    warmup = next((w for w in cliente_data.get('warmups', []) if w['id'] == warmup_id), None)
    if not warmup:
        return jsonify({'success': False, 'error': 'Aquecimento não encontrado'}), 404
    if warmup.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
        return jsonify({'success': False, 'error': 'Acesso negado'}), 403
    warmup['status'] = 'paused' if warmup['status'] == 'active' else 'active'
    save_client_data(current_user)
    return jsonify({'success': True, 'data': warmup}), 200

@app.route('/api/warmup/<int:warmup_id>', methods=['DELETE'])
@token_required
def delete_warmup(current_user, warmup_id):
    try:
        cliente_data = get_client_data(current_user)
        warmup = next((w for w in cliente_data.get('warmups', []) if w['id'] == warmup_id), None)
        if not warmup:
            return jsonify({'success': False, 'error': 'Aquecimento não encontrado'}), 404
        if warmup.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        cliente_data['warmups'].remove(warmup)
        save_client_data(current_user)
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'success',
            'message': f'Warmup "{warmup.get("name")}" deletado por {current_user["email"]}'
        })
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Aquecimento deletado'}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/warmup/test/<int:warmup_id>', methods=['POST'])
@token_required
def test_warmup(current_user, warmup_id):
    try:
        cliente_data = get_client_data(current_user)
        warmup = next((w for w in cliente_data.get('warmups', []) if w['id'] == warmup_id), None)
        if not warmup:
            return jsonify({'success': False, 'error': 'Aquecimento não encontrado'}), 404
        if warmup.get('user_id') != current_user['id'] and current_user.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Acesso negado'}), 403
        
        instances = warmup.get('instances', [])
        phrases = warmup.get('phrases', [])
        
        if len(instances) < 2:
            return jsonify({'success': False, 'error': 'Precisa de pelo menos 2 instâncias'}), 400
        if len(phrases) == 0:
            return jsonify({'success': False, 'error': 'Nenhuma frase cadastrada'}), 400
        
        evo_instances = get_evolution_instances()
        instance_numbers = {}
        
        for inst in evo_instances:
            inst_name = inst.get('name')
            if inst_name in instances:
                owner_jid = inst.get('ownerJid', '')
                if owner_jid:
                    number = owner_jid.split('@')[0]
                    instance_numbers[inst_name] = number
                    print(f"  📱 Instância {inst_name}: número {number}")
        
        instancias_validas = [inst for inst in instances if inst in instance_numbers and instance_numbers[inst]]
        
        if len(instancias_validas) < 2:
            return jsonify({'success': False, 'error': 'Menos de 2 instâncias com número válido'}), 400
        
        import random
        inst1, inst2 = random.sample(instancias_validas, 2)
        numero1 = instance_numbers[inst1]
        numero2 = instance_numbers[inst2]
        frase = random.choice(phrases)
        
        print(f"\n🧪 [TESTE WARMUP] {warmup['name']}: {inst1} ({numero1}) -> {inst2} ({numero2})")
        print(f"💬 Mensagem: {frase}")
        
        success, response = send_humanized_message(inst1, numero2, frase, "Teste Warmup", current_user=current_user)
        
        if success:
            warmup['messages_exchanged'] = warmup.get('messages_exchanged', 0) + 1
            save_client_data(current_user)
            
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'[TESTE] WARMUP {warmup["name"]}: {inst1} enviou para {numero2}: {frase[:50]}...'
            })
            save_client_data(current_user)
            
            return jsonify({
                'success': True,
                'message': f'Mensagem enviada de {inst1} para {numero2}',
                'frase': frase,
                'instancia_origem': inst1,
                'instancia_destino': inst2,
                'numero_destino': numero2
            })
        else:
            return jsonify({'success': False, 'error': f'Erro ao enviar: {response}'}), 500
            
    except Exception as e:
        print(f"❌ Erro no test_warmup: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: RELATÓRIOS
# ============================================
@app.route('/api/reports/campaigns', methods=['GET'])
@token_required
def report_campaigns(current_user):
    try:
        format = request.args.get('format', 'json')
        cliente_data = get_client_data(current_user)
        
        if current_user.get('role') == 'admin':
            user_campaigns = cliente_data.get('campaigns', [])
        else:
            user_campaigns = [c for c in cliente_data.get('campaigns', []) if c.get('user_id') == current_user['id']]
        
        if format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['ID', 'Nome', 'Tipo', 'Status', 'Total', 'Enviados', 'Falhas', 'Criado em'])
            for c in user_campaigns:
                writer.writerow([c['id'], c['name'], c.get('tipo', 'personalizada'), c.get('status', 'pending'), c.get('total', 0), c.get('sent', 0), c.get('failed', 0), c.get('created_at', '')])
            output.seek(0)
            return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=relatorio_campanhas.csv'})
        
        return jsonify({
            'success': True,
            'data': user_campaigns,
            'total': len(user_campaigns),
            'stats': {
                'total_sent': sum(c.get('sent', 0) for c in user_campaigns),
                'total_failed': sum(c.get('failed', 0) for c in user_campaigns),
                'completed': len([c for c in user_campaigns if c.get('status') == 'completed']),
                'processing': len([c for c in user_campaigns if c.get('status') == 'processing']),
                'pending': len([c for c in user_campaigns if c.get('status') == 'pending']),
                'paused': len([c for c in user_campaigns if c.get('status') == 'paused'])
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: DASHBOARD
# ============================================
@app.route('/api/dashboard/metrics', methods=['GET'])
@token_required
def get_metrics(current_user):
    try:
        instances = get_evolution_instances()
        total = len(instances) if isinstance(instances, list) else 0
        online = sum(1 for i in instances if i.get('connectionStatus') in ['open', 'connected']) if isinstance(instances, list) else 0
        offline = total - online
        
        cliente_data = get_client_data(current_user)
        
        if current_user.get('role') == 'admin':
            user_campaigns = cliente_data.get('campaigns', [])
            user_contacts = cliente_data.get('contacts', [])
        else:
            user_campaigns = [c for c in cliente_data.get('campaigns', []) if c.get('user_id') == current_user['id']]
            user_contacts = [c for c in cliente_data.get('contacts', []) if c.get('user_id') == current_user['id']]
        
        plano = get_plano_usuario(current_user)
        instancias_usuario = [i for i in cliente_data.get('instances', []) if i.get('user_id') == current_user['id']]
        
        chat_history = cliente_data.get('chat_history', {})
        hoje = datetime.now().strftime('%Y-%m-%d')
        messages_today = sum(1 for h in chat_history.values() for msg in h 
                           if msg.get('type') == 'sent' and msg.get('timestamp', '').startswith(hoje))
        
        replies_today = sum(1 for h in chat_history.values() for msg in h 
                          if msg.get('type') == 'received' and msg.get('timestamp', '').startswith(hoje))
        
        next_scheduled = None
        for s in cliente_data.get('scheduled_messages', []):
            if s.get('status') == 'pending':
                scheduled_time = datetime.fromisoformat(s['scheduledAt'])
                if scheduled_time > datetime.now():
                    if not next_scheduled or scheduled_time < datetime.fromisoformat(next_scheduled):
                        next_scheduled = s['scheduledAt']
                        break
        
        instancias_atencao = [i for i in instances if i.get('connectionStatus') not in ['open', 'connected']]
        
        logs = cliente_data.get('logs', [])
        total_logs = len([l for l in logs if l.get('type') in ['success', 'error']])
        success_logs = len([l for l in logs if l.get('type') == 'success'])
        taxa_entrega = round((success_logs / total_logs * 100) if total_logs > 0 else 98.4, 1)
        
        messages_by_day = []
        for i in range(6, -1, -1):
            day = datetime.now() - timedelta(days=i)
            day_str = day.strftime('%Y-%m-%d')
            count = sum(1 for h in chat_history.values() for msg in h 
                       if msg.get('type') == 'sent' and msg.get('timestamp', '').startswith(day_str))
            messages_by_day.append({'date': day.strftime('%d/%m'), 'count': count})
        
        return jsonify({
            'success': True,
            'metrics': {
                'total_chips': total,
                'online_chips': online,
                'offline_chips': offline,
                'messages_today': messages_today,
                'replies_today': replies_today,
                'success_rate': taxa_entrega,
                'active_campaigns': len([c for c in user_campaigns if c.get('status') in ['processing', 'pending', 'paused']]),
                'total_contacts': len(user_contacts),
                'total_users': len(cliente_data.get('users', [])),
                'scheduled_messages': len([s for s in cliente_data.get('scheduled_messages', []) if s.get('status') == 'pending']),
                'next_scheduled': next_scheduled,
                'instancias_atencao': len(instancias_atencao),
                'unread_messages': sum(1 for h in chat_history.values() for msg in h if msg.get('type') == 'received' and not msg.get('read')),
                'messages_by_day': messages_by_day,
                'campaigns_by_status': {
                    'completed': len([c for c in user_campaigns if c.get('status') == 'completed']),
                    'processing': len([c for c in user_campaigns if c.get('status') == 'processing']),
                    'pending': len([c for c in user_campaigns if c.get('status') == 'pending']),
                    'scheduled': len([c for c in user_campaigns if c.get('status') == 'scheduled']),
                    'paused': len([c for c in user_campaigns if c.get('status') == 'paused'])
                },
                'plano': {
                    'nome': plano['nome'],
                    'instancias_usadas': len(instancias_usuario),
                    'max_instancias': plano['max_instancias'],
                    'limite_contatos': plano['max_contatos_por_campanha']
                }
            }
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================
# ROTA: CHAT
# ============================================
@app.route('/api/chat/instances', methods=['GET'])
@token_required
def get_chat_instances(current_user):
    try:
        instances = get_evolution_instances()
        cliente_data = get_client_data(current_user)
        chat_history = cliente_data.get('chat_history', {})
        
        if current_user.get('role') != 'admin':
            user_instance_names = [inst.get('name') for inst in cliente_data.get('instances', []) if inst.get('user_id') == current_user['id']]
            instances = [inst for inst in instances if inst.get('name') in user_instance_names]
        
        for inst in instances:
            inst['has_chat'] = True
            inst['unread_count'] = sum(
                1 for msg in chat_history.get(inst.get('name', ''), []) 
                if msg.get('type') == 'received' and not msg.get('read')
            )
        
        return jsonify({'success': True, 'data': instances}), 200
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/<instance_name>', methods=['GET'])
@token_required
def get_chat_history(current_user, instance_name):
    try:
        cliente_data = get_client_data(current_user)
        
        if current_user.get('role') != 'admin':
            user_instance = next((i for i in cliente_data.get('instances', []) if i.get('name') == instance_name and i.get('user_id') == current_user['id']), None)
            if not user_instance:
                return jsonify({'success': False, 'error': 'Acesso negado a esta instância'}), 403
        
        try:
            url = f"{EVO_SERVER}/instance/fetchInstances"
            headers = {"apikey": EVO_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                instances = response.json()
                if isinstance(instances, list):
                    inst = next((i for i in instances if i.get('name') == instance_name), None)
                    if inst:
                        chat_url = f"{EVO_SERVER}/chat/fetchMessages/{instance_name}"
                        chat_response = requests.get(chat_url, headers=headers, timeout=10)
                        if chat_response.status_code == 200:
                            chat_data = chat_response.json()
                            formatted_data = []
                            if isinstance(chat_data, list):
                                for msg in chat_data:
                                    formatted_data.append({
                                        'from': msg.get('from', ''),
                                        'to': msg.get('to', ''),
                                        'message': msg.get('text', msg.get('message', '')),
                                        'timestamp': msg.get('timestamp', datetime.now().isoformat()),
                                        'type': 'sent' if msg.get('fromMe', False) else 'received',
                                        'read': True
                                    })
                            
                            chat_history = cliente_data.get('chat_history', {})
                            local_history = chat_history.get(instance_name, [])
                            all_messages = formatted_data + local_history
                            all_messages.sort(key=lambda x: x.get('timestamp', ''))
                            
                            return jsonify({'success': True, 'data': all_messages}), 200
        except Exception as e:
            print(f"⚠️ Erro ao buscar chat da Evolution API: {e}")
        
        chat_history = cliente_data.get('chat_history', {})
        history = chat_history.get(instance_name, [])
        
        number = request.args.get('number')
        if number:
            number = normalizar_numero(number)
            filtered = [
                msg for msg in history 
                if normalizar_numero(msg.get('from', '')) == number or normalizar_numero(msg.get('to', '')) == number
            ]
            return jsonify({'success': True, 'data': filtered}), 200
        
        return jsonify({'success': True, 'data': history}), 200
        
    except Exception as e:
        print(f"❌ Erro ao buscar histórico do chat: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/<instance_name>/messages', methods=['GET'])
@token_required
def get_chat_messages(current_user, instance_name):
    try:
        number = request.args.get('number')
        if not number:
            return jsonify({'success': False, 'error': 'Número é obrigatório'}), 400
        
        cliente_data = get_client_data(current_user)
        
        if current_user.get('role') != 'admin':
            user_instance = next((i for i in cliente_data.get('instances', []) if i.get('name') == instance_name and i.get('user_id') == current_user['id']), None)
            if not user_instance:
                return jsonify({'success': False, 'error': 'Acesso negado a esta instância'}), 403
        
        number = normalizar_numero(number)
        chat_history = cliente_data.get('chat_history', {})
        history = chat_history.get(instance_name, [])
        
        filtered = [
            msg for msg in history 
            if normalizar_numero(msg.get('from', '')) == number or normalizar_numero(msg.get('to', '')) == number
        ]
        
        filtered.sort(key=lambda x: x.get('timestamp', ''))
        
        try:
            url = f"{EVO_SERVER}/chat/fetchMessages/{instance_name}"
            headers = {"apikey": EVO_API_KEY}
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                chat_data = response.json()
                if isinstance(chat_data, list):
                    for msg in chat_data:
                        msg_number = normalizar_numero(msg.get('from', ''))
                        if msg_number == number or normalizar_numero(msg.get('to', '')) == number:
                            msg_timestamp = msg.get('timestamp', '')
                            exists = any(
                                normalizar_numero(m.get('from', '')) == msg_number and 
                                normalizar_numero(m.get('to', '')) == normalizar_numero(msg.get('to', '')) and
                                abs((datetime.fromisoformat(m.get('timestamp', '1970-01-01')) - 
                                     datetime.fromisoformat(msg_timestamp)).total_seconds()) < 5
                                for m in filtered
                            )
                            if not exists:
                                filtered.append({
                                    'from': msg.get('from', ''),
                                    'to': msg.get('to', ''),
                                    'message': msg.get('text', msg.get('message', '')),
                                    'timestamp': msg_timestamp,
                                    'type': 'sent' if msg.get('fromMe', False) else 'received',
                                    'read': True
                                })
        except Exception as e:
            print(f"⚠️ Erro ao buscar mensagens da Evolution: {e}")
        
        filtered.sort(key=lambda x: x.get('timestamp', ''))
        return jsonify({'success': True, 'data': filtered}), 200
        
    except Exception as e:
        print(f"❌ Erro ao buscar mensagens: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/<instance_name>/send', methods=['POST'])
@token_required
def send_chat_message(current_user, instance_name):
    try:
        data = request.get_json()
        number = data.get('number')
        message = data.get('message')
        
        if not number or not message:
            return jsonify({'success': False, 'error': 'Número e mensagem são obrigatórios'}), 400
        
        cliente_data = get_client_data(current_user)
        
        if current_user.get('role') != 'admin':
            user_instance = next((i for i in cliente_data.get('instances', []) if i.get('name') == instance_name and i.get('user_id') == current_user['id']), None)
            if not user_instance:
                return jsonify({'success': False, 'error': 'Acesso negado a esta instância'}), 403
        
        number = normalizar_numero(number)
        if not number:
            return jsonify({'success': False, 'error': 'Número inválido'}), 400
        
        try:
            headers = {"apikey": EVO_API_KEY}
            check_url = f"{EVO_SERVER}/instance/fetchInstances"
            check_response = requests.get(check_url, headers=headers, timeout=3)
            
            if check_response.status_code == 200:
                instances = check_response.json()
                inst = next((i for i in instances if i.get('name') == instance_name), None)
                if inst:
                    status = inst.get('connectionStatus')
                    print(f"📊 Status da instância {instance_name}: {status}")
        except Exception as e:
            print(f"⚠️ Erro ao verificar instância: {e}")
        
        url = f"{EVO_SERVER}/message/sendText/{instance_name}"
        headers = {
            'Content-Type': 'application/json',
            'apikey': EVO_API_KEY
        }
        payload = {
            'number': number,
            'text': message,
            'options': {
                'delay': 1500,
                'presence': 'composing'
            }
        }
        
        print(f"📤 Enviando mensagem via chat: {instance_name} -> {number}")
        print(f"💬 {message[:100]}{'...' if len(message) > 100 else ''}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code in [200, 201]:
            chat_history = cliente_data.get('chat_history', {})
            if instance_name not in chat_history:
                chat_history[instance_name] = []
            
            chat_history[instance_name].append({
                'from': 'me',
                'to': number,
                'message': message,
                'timestamp': datetime.now().isoformat(),
                'type': 'sent',
                'read': True
            })
            cliente_data['chat_history'] = chat_history
            save_client_data(current_user)
            
            cliente_data['logs'].append({
                'time': datetime.now().isoformat(),
                'type': 'success',
                'message': f'💬 Mensagem enviada via chat: {instance_name} -> {number}'
            })
            save_client_data(current_user)
            
            return jsonify({'success': True, 'data': response.json()}), 200
        
        erro_msg = f"❌ Falha ao enviar mensagem via chat: Status {response.status_code} - {response.text[:200]}"
        print(erro_msg)
        cliente_data['logs'].append({
            'time': datetime.now().isoformat(),
            'type': 'error',
            'message': f'Chat: {erro_msg} - Instância {instance_name} -> {number}'
        })
        save_client_data(current_user)
        
        return jsonify({'success': False, 'error': response.text}), response.status_code
        
    except Exception as e:
        print(f"❌ Erro ao enviar mensagem: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/chat/<instance_name>/mark-read', methods=['POST'])
@token_required
def mark_chat_read(current_user, instance_name):
    try:
        data = request.get_json()
        number = data.get('number')
        
        if not number:
            return jsonify({'success': False, 'error': 'Número é obrigatório'}), 400
        
        cliente_data = get_client_data(current_user)
        chat_history = cliente_data.get('chat_history', {})
        history = chat_history.get(instance_name, [])
        number = normalizar_numero(number)
        
        for msg in history:
            if normalizar_numero(msg.get('from', '')) == number and msg.get('type') == 'received':
                msg['read'] = True
        
        chat_history[instance_name] = history
        cliente_data['chat_history'] = chat_history
        save_client_data(current_user)
        return jsonify({'success': True, 'message': 'Mensagens marcadas como lidas'}), 200
        
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
        'data': {'enabled': True, 'delay': 3, 'context_window': 5}
    }), 200

@app.route('/api/auto-reply/config', methods=['POST'])
@token_required
def update_auto_reply_config(current_user):
    return jsonify({'success': True, 'message': 'Configurações atualizadas'}), 200

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
# THREADS
# ============================================
def check_scheduled_messages():
    while True:
        try:
            now = datetime.now()
            for cliente_id in os.listdir('data'):
                if not os.path.isdir(os.path.join('data', cliente_id)):
                    continue
                cliente_data = load_cliente_data(cliente_id)
                scheduled_messages = cliente_data.get('scheduled_messages', [])
                
                for scheduled in scheduled_messages[:]:
                    if scheduled.get('status') != 'pending':
                        continue
                    scheduled_time = datetime.fromisoformat(scheduled['scheduledAt'])
                    if now >= scheduled_time:
                        campaign_id = scheduled.get('campaign_id')
                        campaign = next((c for c in cliente_data.get('campaigns', []) if c['id'] == campaign_id), None)
                        
                        if campaign:
                            scheduled_messages.remove(scheduled)
                            cliente_data['scheduled_messages'] = scheduled_messages
                            
                            # BUSCA O USUÁRIO REAL QUE CRIOU A CAMPANHA
                            user_id = campaign.get('user_id')
                            user = next((u for u in cliente_data.get('users', []) if u['id'] == user_id), None)
                            
                            if not user:
                                # Se não encontrar, usa o primeiro admin do cliente
                                user = next((u for u in cliente_data.get('users', []) if u.get('role') == 'admin'), None)
                            
                            if user:
                                # Adiciona o cliente_id ao usuário
                                user['cliente_id'] = cliente_id
                                
                                save_cliente_data(cliente_id, cliente_data)
                                print(f"⏰ Executando campanha agendada: {campaign['name']}")
                                cliente_data['logs'].append({
                                    'time': datetime.now().isoformat(),
                                    'type': 'info',
                                    'message': f'Campanha agendada {campaign["name"]} iniciando...'
                                })
                                save_cliente_data(cliente_id, cliente_data)
                                
                                # Executa com o usuário REAL
                                thread = threading.Thread(target=process_campaign, args=(campaign_id, user))
                                thread.daemon = True
                                thread.start()
                            else:
                                print(f"❌ Nenhum usuário encontrado para executar a campanha {campaign_id}")
            time.sleep(30)
        except Exception as e:
            print(f"Erro no verificador: {e}")
            time.sleep(60)

threading.Thread(target=check_scheduled_messages, daemon=True).start()

# ============================================
# WARMUP LOOP (MULTI-CLIENTE)
# ============================================
def process_warmup_loop():
    print("🔄 THREAD DE MATURAÇÃO INICIADA! Aguardando warmups ativos...")
    
    while True:
        try:
            # Verifica warmups em todos os clientes
            for cliente_id in os.listdir('data'):
                if not os.path.isdir(os.path.join('data', cliente_id)):
                    continue
                cliente_data = load_cliente_data(cliente_id)
                warmups_ativos = [w for w in cliente_data.get('warmups', []) if w.get('status') == 'active']
                
                if not warmups_ativos:
                    continue
                
                for warmup in warmups_ativos:
                    instances = warmup.get('instances', [])
                    phrases = warmup.get('phrases', [])
                    min_interval = warmup.get('min_interval', 5)
                    max_interval = warmup.get('max_interval', 15)
                    
                    if len(instances) < 2:
                        print(f"⚠️ Warmup '{warmup['name']}': precisa de pelo menos 2 instâncias")
                        warmup['status'] = 'paused'
                        save_cliente_data(cliente_id, cliente_data)
                        continue
                    
                    if len(phrases) == 0:
                        print(f"⚠️ Warmup '{warmup['name']}': nenhuma frase cadastrada")
                        warmup['status'] = 'paused'
                        save_cliente_data(cliente_id, cliente_data)
                        continue
                    
                    evo_instances = get_evolution_instances()
                    instance_numbers = {}
                    
                    for inst in evo_instances:
                        inst_name = inst.get('name')
                        if inst_name in instances:
                            owner_jid = inst.get('ownerJid', '')
                            if owner_jid:
                                number = owner_jid.split('@')[0]
                                instance_numbers[inst_name] = number
                                print(f"  📱 Instância {inst_name}: número {number}")
                            else:
                                print(f"  ⚠️ Instância {inst_name}: sem número (ownerJid vazio)")
                    
                    instancias_validas = [inst for inst in instances if inst in instance_numbers and instance_numbers[inst]]
                    
                    if len(instancias_validas) < 2:
                        print(f"⚠️ Warmup '{warmup['name']}': menos de 2 instâncias com número válido")
                        warmup['status'] = 'paused'
                        save_cliente_data(cliente_id, cliente_data)
                        continue
                    
                    inst1, inst2 = random.sample(instancias_validas, 2)
                    numero1 = instance_numbers[inst1]
                    numero2 = instance_numbers[inst2]
                    frase = random.choice(phrases)
                    
                    print(f"\n🔄 [WARMUP] {warmup['name']}: {inst1} ({numero1}) -> {inst2} ({numero2})")
                    print(f"💬 Mensagem: {frase}")
                    
                    success1, response1 = send_humanized_message(
                        inst1,
                        numero2,
                        frase,
                        etapa_nome="Aquecimento",
                        current_user=None
                    )
                    
                    if success1:
                        warmup['messages_exchanged'] = warmup.get('messages_exchanged', 0) + 1
                        print(f"✅ [WARMUP] Mensagem enviada: {inst1} -> {numero2}")
                        
                        chat_history = cliente_data.get('chat_history', {})
                        if inst1 not in chat_history:
                            chat_history[inst1] = []
                        chat_history[inst1].append({
                            'from': 'me',
                            'to': numero2,
                            'message': frase,
                            'timestamp': datetime.now().isoformat(),
                            'type': 'sent',
                            'warmup': True,
                            'warmup_name': warmup['name']
                        })
                        cliente_data['chat_history'] = chat_history
                        save_cliente_data(cliente_id, cliente_data)
                        
                        cliente_data['logs'].append({
                            'time': datetime.now().isoformat(),
                            'type': 'success',
                            'message': f'WARMUP: {inst1} enviou para {numero2}: {frase[:50]}...'
                        })
                        save_cliente_data(cliente_id, cliente_data)
                        
                        time.sleep(random.randint(3, 8))
                        
                        frase_resposta = random.choice(phrases)
                        print(f"🔄 [WARMUP] Resposta: {inst2} ({numero2}) -> {inst1} ({numero1})")
                        print(f"💬 Resposta: {frase_resposta}")
                        
                        success2, response2 = send_humanized_message(
                            inst2,
                            numero1,
                            frase_resposta,
                            etapa_nome="Aquecimento (resposta)",
                            current_user=None
                        )
                        
                        if success2:
                            warmup['messages_exchanged'] = warmup.get('messages_exchanged', 0) + 1
                            print(f"✅ [WARMUP] Resposta enviada: {inst2} -> {numero1}")
                            
                            chat_history = cliente_data.get('chat_history', {})
                            if inst2 not in chat_history:
                                chat_history[inst2] = []
                            chat_history[inst2].append({
                                'from': 'me',
                                'to': numero1,
                                'message': frase_resposta,
                                'timestamp': datetime.now().isoformat(),
                                'type': 'sent',
                                'warmup': True,
                                'warmup_name': warmup['name']
                            })
                            cliente_data['chat_history'] = chat_history
                            save_cliente_data(cliente_id, cliente_data)
                            
                            cliente_data['logs'].append({
                                'time': datetime.now().isoformat(),
                                'type': 'success',
                                'message': f'WARMUP: {inst2} respondeu para {numero1}: {frase_resposta[:50]}...'
                            })
                            save_cliente_data(cliente_id, cliente_data)
                        else:
                            print(f"❌ [WARMUP] Falha na resposta: {response2}")
                    else:
                        print(f"❌ [WARMUP] Falha no envio: {response1}")
                    
                    intervalo = random.randint(min_interval, max_interval) * 60
                    print(f"⏳ [WARMUP] Próxima troca em {intervalo} segundos...")
                    print(f"{'='*60}\n")
                    time.sleep(intervalo)
                    
        except Exception as e:
            warmup_name = 'desconhecido'
            try:
                if 'warmup' in locals() and warmup:
                    warmup_name = warmup.get('name', 'desconhecido')
            except:
                pass
            print(f"❌ [WARMUP] Erro no warmup {warmup_name}: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)

def start_warmup_thread():
    warmup_thread = threading.Thread(target=process_warmup_loop, daemon=True)
    warmup_thread.start()
    print("🔄 Thread de Maturação (Warmup) iniciada!")

start_warmup_thread()

@app.route('/api/sequencias', methods=['GET'])
@token_required
def get_sequencias(current_user):
    try:
        cliente_data = get_client_data(current_user)
        return jsonify(cliente_data.get('funis', [])), 200
    except Exception as e:
        print(f"❌ Erro ao buscar sequências: {e}")
        return jsonify({'error': str(e)}), 500

# ============================================
# INICIALIZAÇÃO
# ============================================
if __name__ == '__main__':
    init_database()
    port = int(os.getenv('PORT', 5000))
    print(f"\n{'='*60}")
    print(f"🚀 ZAP OBSIDIAN - Sistema Completo (SEM GROQ)")
    print(f"{'='*60}")
    print(f"📍 URL: http://localhost:{port}")
    print(f"\n👤 Credenciais:")
    print(f"   Admin: admin@zapobsidian.io / senha123 (ACESSO ILIMITADO)")
    print(f"   Demo:  demo@zapobsidian.io / demo123 (7 dias trial)")
    print(f"\n📋 PLANOS DISPONÍVEIS:")
    for plano_id, plano in PLANOS_PADRAO.items():
        print(f"   - {plano['nome']}: {plano['max_instancias']} instâncias, {plano['max_contatos_por_campanha']} contatos/campanha")
    print(f"\n📡 Webhook: ATIVO")
    print(f"📝 Funis Múltiplos: ✅ ATIVO")
    print(f"👥 Multi-usuário: ✅ ATIVO")
    print(f"📎 Upload de Mídia: ✅ ATIVO")
    print(f"💬 Chat View: ✅ ATIVO")
    print(f"🧹 Limpeza de Campanhas: ✅ DISPONÍVEL")
    print(f"📋 Templates: ✅ ATIVO")
    print(f"⏸️ Pausar/Retomar: ✅ ATIVO")
    print(f"✅ Finalizar Campanha: ✅ ATIVO")
    print(f"📊 Relatórios: ✅ ATIVO")
    print(f"🔄 Agendamento: ✅ CORRIGIDO")
    print(f"🎯 Spintax Avançado: ✅ ATIVO")
    print(f"🔔 Notificações: ✅ ATIVO")
    print(f"🌐 Multi-instância: ✅ ATIVO")
    print(f"✅ Validador WhatsApp: ✅ CORRIGIDO (POST)")
    print(f"💰 Sistema de Planos: ✅ ATIVO")
    print(f"⏰ Expiração de Planos: ✅ ATIVO")
    print(f"🔄 Renovação de Planos: ✅ ATIVO")
    print(f"🧠 IA: ❌ REMOVIDA (100% palavras-chave)")
    print(f"🛡️ Proteções anti-loop: ✅ ATIVO")
    print(f"🔗 Teste de Proxy: ✅ ATIVO")
    print(f"📊 Central de Operações: ✅ ATIVO")
    print(f"🔄 Maturação (Warmup): ✅ ATIVO")
    print(f"🏢 Multi-Tenant: ✅ CORRIGIDO")
    print(f"🎭 Variação de Saudação: ✅ IMPLEMENTADO (3 templates aleatórios)")
    print(f"✅ Webhook com current_user: ✅ CORRIGIDO")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=port, debug=False)