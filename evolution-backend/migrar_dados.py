# migrar_dados.py
import os
import json
import shutil

def migrar_dados():
    """Migra os dados do database.json antigo para a estrutura de clientes"""
    
    # 1. Verifica se o database.json existe
    if not os.path.exists('data/database.json'):
        print("❌ Arquivo data/database.json não encontrado!")
        return
    
    # 2. Lê o database antigo
    with open('data/database.json', 'r', encoding='utf-8') as f:
        old_data = json.load(f)
    
    # 3. Cria a pasta default
    os.makedirs('data/default', exist_ok=True)
    
    # 4. Salva no novo formato
    with open('data/default/database.json', 'w', encoding='utf-8') as f:
        json.dump(old_data, f, indent=2, ensure_ascii=False)
    
    # 5. Faz backup do antigo
    shutil.copy('data/database.json', 'data/database_backup.json')
    
    print("✅ Migração concluída!")
    print(f"📁 Dados migrados para: data/default/database.json")
    print(f"💾 Backup criado: data/database_backup.json")
    
    # 6. Mostra os usuários migrados
    users = old_data.get('users', [])
    print(f"\n👤 Usuários migrados: {len(users)}")
    for user in users:
        print(f"   - {user.get('email')} (ID: {user.get('id')})")
    
    # 7. Mostra as instâncias
    instances = old_data.get('instances', [])
    print(f"\n📱 Instâncias migradas: {len(instances)}")
    for inst in instances:
        print(f"   - {inst.get('name')}")

if __name__ == '__main__':
    migrar_dados()