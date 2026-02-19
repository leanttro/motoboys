from flask import Flask, render_template, request, redirect, session, flash, url_for, g, abort
import requests
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_sos_motoboy")

# --- SEGURANÇA NATIVA (SEM BIBLIOTECA EXTERNA) ---
# Dicionário simples na memória para limitar requisições (Rate Limit Artesanal)
request_log = {}

def check_limit(key, limit, period_seconds):
    now = datetime.now()
    if key not in request_log:
        request_log[key] = []
    
    # Limpa logs antigos
    request_log[key] = [t for t in request_log[key] if t > now - timedelta(seconds=period_seconds)]
    
    if len(request_log[key]) >= limit:
        return False
        
    request_log[key].append(now)
    return True

def get_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

# --- CONFIGURAÇÕES ---
DIRECTUS_URL = os.getenv("DIRECTUS_URL", "https://api2.leanttro.com").rstrip('/')
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "") 

# Configurações de E-mail
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 465))
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "True") == "True"

# Serializer para Tokens de Recuperação de Senha
serializer = URLSafeTimedSerializer(app.secret_key)

# LISTA DE DOMÍNIOS DO SISTEMA
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

def send_email(to_email, subject, html_body):
    try:
        msg = MIMEMultipart()
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))

        if MAIL_USE_SSL:
            server = smtplib.SMTP_SSL(MAIL_SERVER, MAIL_PORT)
        else:
            server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
            server.starttls()
            
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.sendmail(MAIL_USERNAME, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Erro ao enviar email: {e}")
        return False

# --- SEGURANÇA: MIDDLEWARE ANTI-BOT ---
@app.before_request
def block_scrapers():
    user_agent = request.headers.get('User-Agent', '').lower()
    bots = ['python-requests', 'curl', 'wget', 'libwww-perl', 'scrapy', 'httpclient']
    if any(bot in user_agent for bot in bots):
        abort(403, description="Acesso negado.")

# --- MIDDLEWARE: VERIFICA DOMÍNIO PRÓPRIO ---
@app.before_request
def verificar_dominio():
    host_atual = request.host.split(':')[0].lower()
    g.perfil_dominio = None
    
    e_sistema = False
    for sys_d in SYSTEM_DOMAINS:
        if sys_d in host_atual:
            e_sistema = True
            break
            
    if not e_sistema:
        try:
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
    if g.perfil_dominio:
        return render_template('sos.html', m=g.perfil_dominio, idade=calcular_idade(g.perfil_dominio.get('data_nascimento')))
    if session.get('motoboy_id'):
        return redirect('/painel')
    return render_template('index.html')

# --- CADASTRO ---
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    # Rate Limit: 10 cadastros por hora por IP
    if not check_limit(f"cad_{get_ip()}", 10, 3600):
        flash("Muitas tentativas. Tente mais tarde.", "error")
        return redirect('/')

    codigo_pre = request.args.get('codigo', '')
    
    if request.method == 'POST':
        slug = request.form.get('slug').lower().strip()
        nome = request.form.get('nome')
        email = request.form.get('email').strip()
        senha = request.form.get('senha')
        
        headers = get_headers()
        
        check_slug = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug}", headers=headers)
        if check_slug.status_code == 200 and len(check_slug.json()['data']) > 0:
            flash('Este código de adesivo já está em uso!', 'error')
            return render_template('cadastro.html', codigo=slug)

        check_email = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[email][_eq]={email}", headers=headers)
        if check_email.status_code == 200 and len(check_email.json()['data']) > 0:
            flash('Este e-mail já está cadastrado!', 'error')
            return render_template('cadastro.html', codigo=slug)

        payload = {
            "status": "published",
            "slug": slug,
            "nome_completo": nome,
            "email": email,
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
    # Rate Limit: 10 tentativas por minuto
    if not check_limit(f"login_{get_ip()}", 10, 60):
        flash("Muitas tentativas. Aguarde.", "error")
        return render_template('login.html')

    if request.method == 'POST':
        email = request.form.get('email').strip()
        senha = request.form.get('senha')
        
        headers = get_headers()
        r = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[email][_eq]={email}", headers=headers)
        data = r.json().get('data')
        
        if data and check_password_hash(data[0]['senha'], senha):
            session['motoboy_id'] = data[0]['id']
            return redirect('/painel')
        else:
            flash('E-mail ou senha incorretos.', 'error')

    return render_template('login.html')

# --- ESQUECEU SENHA ---
@app.route('/esqueceu-senha', methods=['GET', 'POST'])
def esqueceu_senha():
    if request.method == 'POST':
        email = request.form.get('email').strip()
        headers = get_headers()
        
        r = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[email][_eq]={email}", headers=headers)
        data = r.json().get('data')
        
        if data:
            user = data[0]
            token = serializer.dumps(user['email'], salt='recuperar-senha')
            link = url_for('redefinir_senha', token=token, _external=True)
            
            html = f"""
            <h3>Recuperação de Senha - SOS Motoboy</h3>
            <p>Olá {user['nome_completo']},</p>
            <p>Clique no link abaixo para criar uma nova senha:</p>
            <a href="{link}">{link}</a>
            <p>Se você não solicitou, ignore este e-mail.</p>
            """
            
            if send_email(email, "Redefinir Senha - SOS Motoboy", html):
                flash('Link de recuperação enviado para seu e-mail.', 'success')
            else:
                flash('Erro ao enviar e-mail. Tente novamente.', 'error')
        else:
            flash('E-mail não encontrado no sistema.', 'error')
            
    return render_template('esqueceu_senha.html')

# --- REDEFINIR SENHA ---
@app.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    try:
        email = serializer.loads(token, salt='recuperar-senha', max_age=3600)
    except:
        flash('Link inválido ou expirado.', 'error')
        return redirect('/login')
        
    if request.method == 'POST':
        nova_senha = request.form.get('senha')
        headers = get_headers()
        
        r = requests.get(f"{DIRECTUS_URL}/items/motoboys?filter[email][_eq]={email}", headers=headers)
        data = r.json().get('data')
        
        if data:
            user_id = data[0]['id']
            payload = {"senha": generate_password_hash(nova_senha)}
            requests.patch(f"{DIRECTUS_URL}/items/motoboys/{user_id}", headers=headers, json=payload)
            
            flash('Senha alterada com sucesso! Faça login.', 'success')
            return redirect('/login')
            
    return render_template('redefinir_senha.html', token=token)

# --- PAINEL ---
@app.route('/painel', methods=['GET', 'POST'])
def painel():
    mid = session.get('motoboy_id')
    if not mid: return redirect('/login')
    
    headers = get_headers()
    
    if request.method == 'POST':
        dom_proprio = request.form.get('dominio_proprio', '').replace('http://', '').replace('https://', '').rstrip('/')

        payload = {
            "nome_completo": request.form.get('nome'),
            "email": request.form.get('email'),
            "data_nascimento": request.form.get('nascimento'),
            "tipo_sanguineo": request.form.get('sangue'),
            "alergias_condicoes": request.form.get('alergias'),
            "contato_nome": request.form.get('contato_nome'),
            "contato_telefone": request.form.get('contato_tel').replace(' ','').replace('-','').replace('(','').replace(')',''),
            "contato_nome2": request.form.get('contato_nome2'),
            "contato_telefone2": request.form.get('contato_tel2').replace(' ','').replace('-','').replace('(','').replace(')',''),
            "plano_saude": request.form.get('plano'),
            "dominio_proprio": dom_proprio
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