from flask import Flask, render_template, request, jsonify, redirect, url_for, session, g, flash
import requests
import os
import json
import uuid
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Carrega variáveis de ambiente
load_dotenv()

app = Flask(__name__)

# --- CONFIGURAÇÕES GERAIS ---
app.url_map.strict_slashes = False 
app.secret_key = os.getenv("SECRET_KEY", "chave_secreta_super_segura_saas_2026")
DOMINIO_BASE = "leanttro.com"

# Ajuste as URLs conforme seu ambiente
DIRECTUS_URL = os.getenv("DIRECTUS_URL", "https://api2.leanttro.com").rstrip('/')
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "") 
SUPERFRETE_TOKEN = os.getenv("SUPERFRETE_TOKEN", "")
SUPERFRETE_URL = os.getenv("SUPERFRETE_URL", "https://api.superfrete.com/api/v0/calculator")

def get_headers():
    return {"Authorization": f"Bearer {DIRECTUS_TOKEN}", "Content-Type": "application/json"}

def get_img_url(img_id):
    if not img_id: return ""
    return f"{DIRECTUS_URL}/assets/{img_id}"

# ============================================================================
# ROTA HÍBRIDA (MOTOBOY + LOJA)
# ============================================================================
# Esta rota captura TUDO que vem depois do domínio.
# 1. Verifica se é um MOTOBOY (ex: /001). Se for, exibe SOS.
# 2. Se não, verifica se é uma LOJA.
# ============================================================================

@app.route('/<slug>')
def rota_principal(slug):
    slug_limpo = slug.lower().strip()
    
    # Ignora arquivos de sistema
    if slug_limpo in ['favicon.ico', 'static', 'robots.txt', 'sitemap.xml']:
        return "", 404

    # --- 1. ENXERTO SOS MOTOBOY ---
    # Tenta achar um motoboy com esse código
    try:
        url_moto = f"{DIRECTUS_URL}/items/motoboys?filter[slug][_eq]={slug_limpo}&limit=1"
        r_moto = requests.get(url_moto, headers=get_headers(), timeout=2)
        
        if r_moto.status_code == 200:
            data_moto = r_moto.json().get('data')
            if data_moto:
                # É UM MOTOBOY! Renderiza o SOS e PARA AQUI.
                motoboy = data_moto[0]
                motoboy['foto_url'] = get_img_url(motoboy.get('foto'))
                
                # Calcula idade se tiver data
                idade = ""
                if motoboy.get('data_nascimento'):
                    try:
                        born = datetime.strptime(motoboy['data_nascimento'], "%Y-%m-%d")
                        today = datetime.today()
                        idade = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    except: pass

                return render_template('sos_enxerto.html', m=motoboy, idade=idade)
    except Exception as e:
        print(f"Erro check Motoboy: {e}")
    # --- FIM DO ENXERTO ---


    # --- 2. FLUXO NORMAL DA LOJA (Código Original) ---
    # Se não é motoboy, tenta carregar como Loja
    try:
        # Busca a loja pelo slug
        r = requests.get(f"{DIRECTUS_URL}/items/lojas?filter[slug][_eq]={slug_limpo}", headers=get_headers())
        data = r.json().get('data')

        if not data:
            # Loja não encontrada (Mostra seu erro 404 padrão)
            return render_template('404.html', slug=slug), 404

        loja = data[0]
        g.loja = loja # Salva no contexto global
        
        # Carrega dados da loja (Produtos, Categorias, etc)
        # Buscar Categorias
        r_cat = requests.get(f"{DIRECTUS_URL}/items/categorias?filter[loja][_eq]={loja['id']}&sort=ordem", headers=get_headers())
        categorias = r_cat.json().get('data', [])

        # Buscar Produtos
        r_prod = requests.get(f"{DIRECTUS_URL}/items/produtos?filter[loja][_eq]={loja['id']}&filter[status][_eq]=published", headers=get_headers())
        produtos_raw = r_prod.json().get('data', [])
        
        # Processa imagens dos produtos
        produtos = []
        novidades = []
        for p in produtos_raw:
            p['imagem'] = get_img_url(p['foto_principal']) if p.get('foto_principal') else "https://placehold.co/300"
            produtos.append(p)
            if p.get('destaque'):
                novidades.append(p)

        # Buscar Posts do Blog
        r_blog = requests.get(f"{DIRECTUS_URL}/items/posts?filter[loja][_eq]={loja['id']}&sort=-date_created&limit=3", headers=get_headers())
        posts = []
        for post in r_blog.json().get('data', []):
            post['capa'] = get_img_url(post['capa'])
            # Formata data
            try:
                dt = datetime.strptime(post['date_created'], "%Y-%m-%dT%H:%M:%S.%fZ")
                post['data'] = dt.strftime("%d/%m/%Y")
            except:
                post['data'] = ""
            posts.append(post)

        # Trata Layout (Banners, etc)
        layout_order = loja.get('layout_ordem', 'banner,busca,banners_menores,categorias,produtos,novidades,blog').split(',')
        
        # Processa URLs de imagem da loja
        loja['logo'] = get_img_url(loja.get('logo'))
        loja['banner1'] = get_img_url(loja.get('banner_principal_1'))
        loja['bannermenor1'] = get_img_url(loja.get('banner_menor_1'))
        loja['bannermenor2'] = get_img_url(loja.get('banner_menor_2'))
        
        # Dados para o template
        loja['slug_url'] = slug_limpo

        # Filtro de Categoria via GET
        cat_id = request.args.get('categoria')
        produtos_exibicao = produtos
        if cat_id:
            produtos_exibicao = [p for p in produtos if str(p.get('categoria')) == str(cat_id)]

        return render_template('index.html', 
                             loja=loja, 
                             layout=layout_order, 
                             categorias=categorias, 
                             produtos=produtos_exibicao,
                             novidades=novidades,
                             posts=posts)

    except Exception as e:
        print(f"Erro Loja: {e}")
        return "Erro interno do servidor", 500


# --- OUTRAS ROTAS DO SISTEMA (MANTIDAS) ---

@app.route('/')
def home():
    return redirect("https://leanttro.com") # Redireciona raiz para institucional

# Rota de Cadastro de Loja
@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro_loja():
    if request.method == 'POST':
        nome = request.form.get('nome')
        slug = request.form.get('slug').lower().strip()
        email = request.form.get('email')
        senha = request.form.get('senha')
        whatsapp = request.form.get('whatsapp')
        
        # Verifica duplicidade
        check = requests.get(f"{DIRECTUS_URL}/items/lojas?filter[slug][_eq]={slug}", headers=get_headers())
        if check.json().get('data'):
            flash('Este link de loja já existe. Escolha outro.', 'error')
            return render_template('cadastro.html')
            
        payload = {
            "status": "published",
            "nome": nome,
            "slug": slug,
            "email_admin": email,
            "senha_admin": generate_password_hash(senha),
            "whatsapp_comercial": whatsapp,
            "cor_primaria": "#db2777" # Cor padrão rosa
        }
        
        r = requests.post(f"{DIRECTUS_URL}/items/lojas", headers=get_headers(), json=payload)
        
        if r.status_code in [200, 201]:
            return redirect(f"/{slug}/admin")
        else:
            flash("Erro ao criar loja. Tente novamente.", 'error')
            
    return render_template('cadastro.html')

# Rota de Admin da Loja
@app.route('/<loja_slug>/admin', methods=['GET', 'POST'])
def admin_loja(loja_slug):
    # Verifica Loja
    r = requests.get(f"{DIRECTUS_URL}/items/lojas?filter[slug][_eq]={loja_slug}", headers=get_headers())
    data = r.json().get('data')
    if not data: return "Loja não encontrada", 404
    loja = data[0]
    
    # Login
    if request.method == 'POST':
        senha = request.form.get('senha')
        if check_password_hash(loja['senha_admin'], senha):
            session[f'admin_{loja_slug}'] = True
            return redirect(f"/{loja_slug}/painel")
        else:
            flash("Senha incorreta", 'error')

    loja_visual = {**loja, "logo": get_img_url(loja.get('logo')), "slug_url": loja_slug}
    return render_template('login_admin.html', loja=loja_visual)

# Rota do Painel (Simplificada para o exemplo)
@app.route('/<loja_slug>/painel')
def painel_loja(loja_slug):
    if not session.get(f'admin_{loja_slug}'): return redirect(f"/{loja_slug}/admin")
    return f"Painel da Loja {loja_slug} (Carregado com sucesso)" 
    # (Aqui viria seu render_template('painel.html') completo)

# Rota de Recuperar Senha
@app.route('/<loja_slug>/recuperar-senha', methods=['GET', 'POST'])
def recuperar_senha(loja_slug):
    r = requests.get(f"{DIRECTUS_URL}/items/lojas?filter[slug][_eq]={loja_slug}", headers=get_headers())
    if not r.json().get('data'): return "Loja não encontrada", 404
    loja = r.json()['data'][0]

    if request.method == 'POST':
        email = request.form.get('email')
        if email == loja.get('email_admin'):
            # Gera token simples (UUID)
            token = str(uuid.uuid4())
            # Salva token no Directus (campo reset_token na tabela lojas)
            requests.patch(f"{DIRECTUS_URL}/items/lojas/{loja['id']}", 
                         headers=get_headers(), 
                         json={'reset_token': token})
            
            # (Aqui você enviaria o email real)
            flash(f'Link de recuperação enviado para {email} (Simulação: /{loja_slug}/nova-senha/{token})', 'success')
        else:
            flash('E-mail não corresponde ao cadastro desta loja.', 'error')
    
    loja_visual = {**loja, "logo": get_img_url(loja.get('logo')), "slug_url": loja_slug}
    return render_template('esqueceu_senha.html', loja=loja_visual)

@app.route('/<loja_slug>/nova-senha/<token>', methods=['GET', 'POST'])
def nova_senha(loja_slug, token):
    # Verifica token
    r = requests.get(f"{DIRECTUS_URL}/items/lojas?filter[reset_token][_eq]={token}", headers=get_headers())
    data = r.json().get('data')
    
    if not data: return "Link inválido ou expirado.", 400
    loja_alvo = data[0]

    if request.method == 'POST':
        nova = request.form.get('senha')
        hash_senha = generate_password_hash(nova)
        
        requests.patch(f"{DIRECTUS_URL}/items/lojas/{loja_alvo['id']}", 
                     headers=get_headers(),
                     json={'senha_admin': hash_senha, 'reset_token': None})
        
        flash('Senha alterada com sucesso! Faça login.', 'success')
        return redirect(f'/{loja_slug}/admin')

    return render_template('nova_senha.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)