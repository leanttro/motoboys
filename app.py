from flask import Flask, render_template, request, redirect, session, flash, url_for, g
import requests
import os
from datetime import datetime
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_sos_motoboy")

# --- CONFIGURAÇÕES ---
DIRECTUS_URL = os.getenv("DIRECTUS_URL", "https://api2.leanttro.com").rstrip('/')
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "") 

# LISTA DE DOMÍNIOS DO SISTEMA (QUE NÃO DEVEM BUSCAR PERFIL AUTOMÁTICO)
# Adicione aqui todos os domínios onde o sistema roda como "Plataforma"
SYSTEM_DOMAINS = [
    'motoboys.leanttro.com',
    'sos.leanttro.com',
    'localhost',
    '127.0.0.1'
]

def get_headers():
    return {"Authorization": f"Bearer {DIRECTUS_TOKEN}", "Content-Type": "application/json"}

def get_upload_headers():
    return {"Authorization": f"Bearer {DIRECTUS_TOKEN}"}

def get_img_url(image_id):
    if not image_id: return "https://placehold.co/400x400?text=Sem+Foto"
    return f"{DIRECTUS_URL}/assets/{image_id}"

def upload_file(file_storage):
    try:
        url = f"{DIRECTUS_URL}/files"
        filename = secure_filename(file_storage.filename)
        files = {'file': (filename, file_storage, file_storage.mimetype)}
        response = requests.post(url, headers=get_upload_headers(), files=files)
        if response.status_code in [200, 201]:
            return response.json()['data']['id']
    except Exception as e:
        print(f"Erro Upload: {e}")
    return None

def calcular_idade(data_nasc):
    if not data_nasc: return ""
    try:
        born = datetime.strptime(data_nasc, "%Y-%m-%d")
        today = datetime.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except:
        return ""

# --- MIDDLEWARE: VERIFICA DOMÍNIO PRÓPRIO ---
@app.before_request
def verificar_dominio():
    # Remove porta se existir (ex: leanttro.com:5000 -> leanttro.com)
    host_atual = request.host.split(':')[0].lower()
    
    g.perfil_dominio = None
    
    # Se o host NÃO for um dos domínios do sistema, tenta achar um motoboy dono desse domínio
    # Verifica se o host atual contém algum dos domínios de sistema (para pegar subdomínios também)
    e_sistema = False
    for sys_d in SYSTEM_DOMAINS:
        if sys_d in host_atual:
            e_sistema = True
            break
            
    if not e_sistema:
        try:
            # Busca motoboy pelo campo dominio_proprio
            # Importante: O motoboy deve cadastrar o domínio exatamente como acessa (ex: www.joao.com.br)
            headers = get_headers()
            url = f"{DIRECTUS_URL}/items/motoboys?filter[dominio_proprio][_eq]={host_atual}&limit=1"
            r = requests.get(url, headers=headers)
            data = r.json().get('data')
            
            if data:
                usuario = data[0]
                usuario['foto_url'] = get_img_url(usuario.get('foto'))
                g.perfil_dominio = usuario
        except Exception as e:
            print(f"Erro verificando domínio: {e}")

# --- ROTA RAIZ (HOME) ---
@app.route('/')
def index():
    # 1. SE FOR DOMÍNIO PRÓPRIO (ex: www.joao.com.br), ABRE O PERFIL DIRETO
    if g.perfil_dominio:
        return render_template('sos.html', m=g.perfil_dominio, idade=calcular_idade(g.perfil_dominio.get('data_nascimento')))

    # 2. SE JÁ TIVER LOGADO, VAI PRO PAINEL
    if session.get('motoboy_id'):
        return redirect('/painel')
        
    # 3. SE NÃO, MOSTRA A LANDING PAGE DO SISTEMA
    return render_template('index.html')

# --- CADASTRO ---
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    codigo_pre = request.args.get('codigo', '')
    
    if request.method == 'POST':
        slug = request.form.get('slug').lower().strip()
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        
        headers = get_headers()
        # Verifica duplicidade
        check = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}", headers=headers)
        
        if check.status_code == 200 and len(check.json()['data']) > 0:
            flash('Este código de adesivo já está em uso!', 'error')
            return render_template('cadastro.html', codigo=slug)

        payload = {
            "status": "published",
            "slug": slug,
            "nome_completo": nome,
            "senha": generate_password_hash(senha)
        }

        try:
            r = requests.post(f"{DIRECTUS_URL}/items/motoboys", headers=headers, json=payload)
            if r.status_code in [200, 201]:
                motoboy_id = r.json()['data']['id']
                session['motoboy_id'] = motoboy_id
                flash('Cadastro realizado! Preencha seus dados.', 'success')
                return redirect('/painel')
            else:
                flash(f'Erro ao cadastrar: {r.text}', 'error')
        except Exception as e:
            flash('Erro de conexão.', 'error')

    return render_template('cadastro.html', codigo=codigo_pre)

# --- LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        slug = request.form.get('slug').lower().strip()
        senha = request.form.get('senha')
        
        headers = get_headers()
        r = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}", headers=headers)
        data = r.json().get('data')
        
        if data and check_password_hash(data[0]['senha'], senha):
            session['motoboy_id'] = data[0]['id']
            return redirect('/painel')
        else:
            flash('Código ou senha incorretos.', 'error')

    return render_template('login.html')

# --- PAINEL ---
@app.route('/painel', methods=['GET', 'POST'])
def painel():
    mid = session.get('motoboy_id')
    if not mid: return redirect('/login')
    
    headers = get_headers()
    
    if request.method == 'POST':
        # Limpa o domínio para salvar limpo (sem http/https e barra final)
        dom_proprio = request.form.get('dominio_proprio', '').replace('http://', '').replace('https://', '').rstrip('/')

        payload = {
            "nome_completo": request.form.get('nome'),
            "data_nascimento": request.form.get('nascimento'),
            "tipo_sanguineo": request.form.get('sangue'),
            "alergias_condicoes": request.form.get('alergias'),
            "contato_nome": request.form.get('contato_nome'),
            "contato_telefone": request.form.get('contato_tel').replace(' ','').replace('-','').replace('(','').replace(')',''),
            "plano_saude": request.form.get('plano'),
            "dominio_proprio": dom_proprio # SALVA O DOMÍNIO AQUI
        }
        
        f = request.files.get('foto')
        if f and f.filename:
            fid = upload_file(f)
            if fid: payload['foto'] = fid
            
        requests.patch(f"{DIRECTUS_URL}/items/motoboys/{mid}", headers=headers, json=payload)
        flash('Dados atualizados com sucesso!', 'success')
        return redirect('/painel')

    # GET
    r = requests.get(f"{DIRECTUS_URL}/items/motoboys/{mid}", headers=headers)
    if r.status_code != 200: return redirect('/logout')
    
    user = r.json()['data']
    user['foto_url'] = get_img_url(user.get('foto'))
    
    return render_template('painel.html', user=user)

# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- ROTA PÚBLICA (SOS por Slug) ---
@app.route('/<slug>')
def perfil_publico(slug):
    slug = slug.lower().strip()
    if slug in ['static', 'favicon.ico']: return ""

    # Se já estamos num domínio próprio vendo um perfil, 
    # acessar /algo pode ser redundante, mas mantemos a lógica.
    
    headers = get_headers()
    url = f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}&limit=1"
    
    try:
        r = requests.get(url, headers=headers)
        data = r.json().get('data')
        
        if not data:
            return redirect(f'/cadastro?codigo={slug}')
            
        motoboy = data[0]
        motoboy['foto_url'] = get_img_url(motoboy.get('foto'))
        
        return render_template('sos.html', m=motoboy, idade=calcular_idade(motoboy.get('data_nascimento')))
        
    except Exception as e:
        return "Erro ao carregar perfil."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)