from flask import Flask, render_template, request, redirect, session, flash, url_for
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
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "") # Token com permissão de escrita em 'motoboys'

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

# --- ROTA RAIZ (HOME) ---
@app.route('/')
def index():
    if session.get('motoboy_id'):
        return redirect('/painel')
    return render_template('index.html')

# --- CADASTRO (ATIVAR ADESIVO) ---
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    codigo_pre = request.args.get('codigo', '')
    
    if request.method == 'POST':
        slug = request.form.get('slug').lower().strip() # O CÓDIGO DO ADESIVO
        nome = request.form.get('nome')
        senha = request.form.get('senha')
        
        # Verifica se o código já existe
        headers = get_headers()
        check = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}", headers=headers)
        
        if check.status_code == 200 and len(check.json()['data']) > 0:
            flash('Este código de adesivo já está em uso ou cadastrado!', 'error')
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
                flash('Cadastro realizado! Preencha seus dados de emergência.', 'success')
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

# --- PAINEL (EDITAR DADOS) ---
@app.route('/painel', methods=['GET', 'POST'])
def painel():
    mid = session.get('motoboy_id')
    if not mid: return redirect('/login')
    
    headers = get_headers()
    
    if request.method == 'POST':
        payload = {
            "nome_completo": request.form.get('nome'),
            "data_nascimento": request.form.get('nascimento'),
            "tipo_sanguineo": request.form.get('sangue'),
            "alergias_condicoes": request.form.get('alergias'),
            "contato_nome": request.form.get('contato_nome'),
            "contato_telefone": request.form.get('contato_tel').replace(' ','').replace('-','').replace('(','').replace(')',''),
            "plano_saude": request.form.get('plano')
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
    user = r.json()['data']
    user['foto_url'] = get_img_url(user.get('foto'))
    
    return render_template('painel.html', user=user)

# --- LOGOUT ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- ROTA DO QR CODE (PERFIL PÚBLICO) ---
# Captura qualquer coisa (001, joao, etc)
@app.route('/<slug>')
def perfil_publico(slug):
    slug = slug.lower().strip()
    
    # Ignora arquivos estáticos se passarem
    if slug in ['static', 'favicon.ico']: return ""

    headers = get_headers()
    url = f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}&limit=1"
    
    try:
        r = requests.get(url, headers=headers)
        data = r.json().get('data')
        
        # SE NÃO EXISTE: Manda para cadastro ativando esse código
        if not data:
            return redirect(f'/cadastro?codigo={slug}')
            
        motoboy = data[0]
        motoboy['foto_url'] = get_img_url(motoboy.get('foto'))
        
        # Lógica simples de idade
        idade = ""
        if motoboy.get('data_nascimento'):
            born = datetime.strptime(motoboy['data_nascimento'], "%Y-%m-%d")
            today = datetime.today()
            idade = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            
        return render_template('sos.html', m=motoboy, idade=idade)
        
    except Exception as e:
        return "Erro ao carregar perfil."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)