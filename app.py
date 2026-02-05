import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import storage
import requests
from datetime import datetime, timedelta
import re

# --- CONFIGURATION ---
load_dotenv()
st.set_page_config(page_title="MOKAFAD - Solution Soumission IA", page_icon="⚡", layout="wide")

# --- LOGO MOKAFAD ---
MOKAFAD_LOGO_URL = "https://unhbihdenqzokxiednos.supabase.co/storage/v1/object/public/logos/logo-mokafad.png"

# --- STYLE BLEU CIEL + LOGO DANS LE TITRE ---
st.markdown(f"""
<style>
    [data-testid="stAppViewContainer"] {{
        background-color: #F0F8FF;
    }}
    [data-testid="stSidebar"] {{
        background-color: white;
        border-right: 2px solid #B0E0E6;
    }}
    .stButton>button {{
        background-color: #1E90FF !important;
        color: white !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.8rem !important;
        font-weight: 600 !important;
        width: auto !important;
        margin: 0.5rem auto !important;
        display: block !important;
        box-shadow: 0 2px 4px rgba(30, 144, 255, 0.3) !important;
    }}
    .stButton>button:hover {{
        background-color: #104E8B !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(30, 144, 255, 0.4) !important;
    }}
    .stTabs [data-baseweb="tab"] {{
        color: #104E8B !important;
        font-weight: 600 !important;
    }}
    .stTabs [aria-selected="true"] {{
        color: white !important;
        background-color: #1E90FF !important;
        border-radius: 8px 8px 0 0 !important;
    }}
    h1, h2, h3 {{
        color: #104E8B !important;
    }}
    div[data-testid="stMetricValue"] {{
        color: #104E8B !important;
    }}
</style>

<div style="display: flex; align-items: center; gap: 12px; margin-bottom: 20px;">
    <img src="{MOKAFAD_LOGO_URL}" width="48" style="border-radius: 8px;">
    <h1 style="margin: 0; color: #104E8B; font-weight: 700;">MOKAFAD - Solution Soumission IA</h1>
</div>
""", unsafe_allow_html=True)

# --- UTILITAIRES DATE ---
def is_business_day(date):
    return date.weekday() < 5

def add_business_days(start_date, days):
    current = start_date
    while days > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            days -= 1
    return current

# --- VÉRIFICATION DES CLÉS ---
required_vars = ["SUPABASE_URL", "SUPABASE_ANON_KEY"]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    st.error(f"❌ Variables manquantes dans .env : {', '.join(missing)}")
    st.stop()

# --- CLIENT SUPABASE ---
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_ANON_KEY")
)

# ============================================
# 🆕 SYSTÈME DE FALLBACK GROQ → GEMINI
# ============================================

class LLMManager:
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        if os.getenv("GROQ_API_KEY"):
            self.providers.append({
                "name": "Groq LLaMA 3.3 70B",
                "api_key": os.getenv("GROQ_API_KEY"),
                "type": "groq"
            })
        if os.getenv("GEMINI_API_KEY"):
            try:
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                model = genai.GenerativeModel('gemini-2.0-flash-exp')
                self.providers.append({
                    "name": "Gemini 2.0 Flash",
                    "client": model,
                    "type": "gemini"
                })
            except Exception as e:
                st.warning(f"⚠️ Gemini non disponible: {str(e)[:100]}")
        if not self.providers:
            st.error("❌ Aucun LLM configuré ! Ajoutez GROQ_API_KEY ou GEMINI_API_KEY dans .env")
            st.stop()
    
    def analyze(self, prompt: str, max_tokens: int = 2000) -> dict:
        for provider in self.providers:
            try:
                if provider["type"] == "groq":
                    response = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {provider['api_key']}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0.3
                        },
                        timeout=30
                    )
                    response.raise_for_status()
                    return {
                        "success": True,
                        "result": response.json()["choices"][0]["message"]["content"],
                        "provider": provider["name"],
                        "error": None
                    }
                elif provider["type"] == "gemini":
                    response = provider["client"].generate_content(
                        prompt,
                        generation_config={"max_output_tokens": max_tokens, "temperature": 0.3}
                    )
                    return {
                        "success": True,
                        "result": response.text,
                        "provider": provider["name"],
                        "error": None
                    }
            except Exception:
                continue
        return {
            "success": False,
            "result": None,
            "provider": None,
            "error": "Tous les LLMs sont indisponibles. Réessayez plus tard."
        }

llm_manager = LLMManager()

# ============================================
# SESSION & FONCTIONS UTILITAIRES
# ============================================

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile_completed' not in st.session_state:
    st.session_state.profile_completed = False
if 'access_token' not in st.session_state:
    st.session_state.access_token = None

def apply_supabase_auth():
    token = st.session_state.get('access_token')
    if token and isinstance(token, str) and token.strip():
        supabase.postgrest.auth(token)

# --- FONCTIONS BASE DE DONNÉES ---
def signup_user(data):
    try:
        supabase.auth.sign_up({
            "email": data["contact_email"], 
            "password": data["password"]
        })
        import time
        time.sleep(2)

        session = supabase.auth.sign_in_with_password({
            "email": data["contact_email"], 
            "password": data["password"]
        })

        if not session or not getattr(session, 'session', None) or not session.session.access_token:
            raise ValueError("Impossible de récupérer le token d'accès après connexion")

        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        entreprise_data = {
            "nom_entreprise": data["nom_entreprise"],
            "numero_neq": data["numero_neq"],
            "licence_rbq": data["licence_rbq"],
            "specialites": data["specialites"],
            "adresse": data["adresse"],
            "ville": data["ville"],
            "province": data["province"],
            "code_postal": data["code_postal"],
            "pays": data["pays"],
            "contact_nom": data["contact_nom"],
            "contact_telephone": data["contact_telephone"],
            "contact_email": data["contact_email"],
            "user_id": session.user.id
        }

        result = supabase.table('entreprises').insert(entreprise_data).execute()
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = False
            return True
        else:
            st.error("❌ Aucune donnée retournée après inscription")
            return False

    except Exception as e:
        st.error(f"❌ Erreur inscription: {str(e)}")
        return False

def login_user(email, password):
    try:
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            return True
        return False
    except Exception as e:
        st.error(f"❌ Erreur connexion: {str(e)}")
        return False

def get_user_by_email(email):
    result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
    return result.data[0] if result.data else None

def update_entreprise_logo(entreprise_id, logo_url):
    apply_supabase_auth()
    supabase.table('entreprises').update({"logo_url": logo_url}).eq('id', entreprise_id).execute()
    # 🔁 Recharger l'utilisateur pour refléter le changement
    user_updated = supabase.table('entreprises').select("*").eq('id', entreprise_id).execute()
    if user_updated.data:
        st.session_state.user = user_updated.data[0]

def add_projet_antecedent(projet_data):
    try:
        apply_supabase_auth()
        data = {
            "entreprise_id": st.session_state.user['id'],
            "nom_projet": projet_data["nom_projet"],
            "montant": projet_data["montant"],
            "duree_jours": projet_data["duree_jours"],
            "specifications": projet_data["specifications"]
        }
        if projet_data.get("document"):
            doc_url = storage.upload_document_projet(supabase, projet_data["document"])
            if doc_url:
                data["document_url"] = doc_url
        supabase.table('projets_antecedents').insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Erreur ajout projet: {str(e)}")
        return False

def save_soumission(entreprise_id, soumission_data):
    try:
        apply_supabase_auth()
        data_to_save = {
            "entreprise_id": entreprise_id,
            "numero_projet": soumission_data.get("numero_projet"),
            "nom_projet": soumission_data.get("nom_projet"),
            "analyse_json": soumission_data.get("analyse_json"),
            "recommendation": soumission_data.get("recommendation"),
            "score": soumission_data.get("score"),
            "statut": soumission_data.get("statut")
        }
        if soumission_data.get("document"):
            try:
                doc_url = storage.upload_soumission(supabase, soumission_data["document"])
                if doc_url:
                    data_to_save["document_url"] = doc_url
            except Exception:
                pass
        result = supabase.table('soumissions').insert(data_to_save).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Erreur sauvegarde soumission: {str(e)}")
        return None

# --- APPLICATION PRINCIPALE ---

if st.session_state.logged_in and st.session_state.access_token:
    apply_supabase_auth()

# --- AUTHENTIFICATION ---
if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["🔐 Connexion", "📝 Inscription"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("📧 Email")
            password = st.text_input("🔒 Mot de passe", type="password")
            if st.form_submit_button("➡️ Se connecter", use_container_width=False):
                if login_user(email, password):
                    st.success("✅ Connecté !")
                    st.rerun()
    with tab2:
        signup_data = forms.signup_form()
        if signup_data:  # ✅ CORRECTION ICI
            if get_user_by_email(signup_data["contact_email"]):
                st.error("❌ Cet email est déjà utilisé")
            elif signup_user(signup_data):
                st.success("✅ Compte créé ! Veuillez compléter votre profil.")
                st.rerun()

# --- PROFIL À COMPLÉTER ---
elif not st.session_state.profile_completed:
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    profile_data = forms.profile_completion_form(st.session_state.user)
    if profile_data:  # ✅ CORRECTION ICI
        apply_supabase_auth()
        if profile_data["logo_file"]:
            try:
                logo_url = storage.upload_logo(supabase, profile_data["logo_file"])
                if logo_url:
                    update_entreprise_logo(st.session_state.user['id'], logo_url)
            except Exception as e:
                st.warning(f"⚠️ Logo non uploadé: {str(e)}")
        for projet in profile_data["projets"]:
            add_projet_antecedent(projet)
        st.session_state.profile_completed = True
        st.success("✅ Profil complété ! Redirection...")
        st.rerun()

# --- APPLICATION PRINCIPALE ---
else:
    user = st.session_state.user
    with st.sidebar:
        # Logo MOKAFAD en haut de la sidebar
        st.markdown(
            f'<div style="text-align: center; margin-bottom: 20px;"><img src="{MOKAFAD_LOGO_URL}" width="80"></div>',
            unsafe_allow_html=True
        )
        if user.get('logo_url'):
            st.image(user['logo_url'], width=150)
        st.write(f"👤 **{user['contact_nom']}**")
        st.write(f"🏢 **{user['nom_entreprise']}**")
        st.write(f"📍 {user['ville']}, {user['province']}")
        if st.button("🚪 Déconnexion", use_container_width=False):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()
    
    # Charger les projets antérieurs
    apply_supabase_auth()
    projets_response = supabase.table('projets_antecedents').select("*").eq('entreprise_id', user['id']).execute()
    projets_antecedents = projets_response.data or []

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Tableau de bord", 
        "🔍 Nouvelle analyse", 
        "🏗️ Projets antérieurs", 
        "👤 Mon profil"
    ])
    
    with tab1:
        st.header("📊 Tableau de bord")
        apply_supabase_auth()
        col1, col2, col3 = st.columns(3)
        with col1:
            projets = supabase.table('projets_antecedents').select("id", count="exact").eq('entreprise_id', user['id']).execute()
            st.metric("🏗️ Projets réalisés", projets.count)
        with col2:
            soumissions = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).execute()
            st.metric("📄 Soumissions analysées", soumissions.count)
        with col3:
            qualifies = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).eq('statut', 'qualifie').execute()
            st.metric("✅ Qualifiées", qualifies.count)
        st.markdown("---")
        st.subheader("📈 Dernières analyses")
        recent = supabase.table('soumissions').select("*").eq('entreprise_id', user['id']).order('created_at', desc=True).limit(5).execute()
        if recent.data:
            for item in recent.data:
                with st.expander(f"📄 {item.get('nom_projet', 'Sans nom')} - {item['created_at'][:10]}"):
                    st.write(f"**Statut:** {item['statut']}")
                    st.write(f"**Recommandation:** {item.get('recommendation', 'N/A')}")
                    st.write(f"**Score:** {item.get('score', 'N/A')}")
                    if item.get('analyse_json') and isinstance(item['analyse_json'], dict):
                        llm_used = item['analyse_json'].get('llm_used', 'N/A')
                        st.write(f"**Modèle IA:** {llm_used}")
        else:
            st.info("📭 Aucune analyse récente")
    
    with tab2:
        st.header("🔍 Lancer une préqualification")
        with st.form("analyse_form"):
            numero_projet = st.text_input("🔢 Numéro du projet")
            nom_projet = st.text_input("📋 Nom du projet")
            uploaded_file = st.file_uploader("📄 PDF Appel d'offre", type=['pdf'])
            submit = st.form_submit_button("🚀 Lancer l'analyse", use_container_width=False)
        
        if submit and uploaded_file:
            with st.spinner("🤖 Analyse IA en cours..."):
                try:
                    reader = PdfReader(uploaded_file)
                    text = " ".join([page.extract_text() or "" for page in reader.pages])[:8000]
                    
                    today = datetime.today()
                    deadline_min = add_business_days(today, 5).strftime("%Y-%m-%d")
                    visit_min = add_business_days(today, 3).strftime("%Y-%m-%d")
                    today_str = today.strftime("%Y-%m-%d")

                    specialites_str = " ".join(user.get('specialites', [])).lower()
                    categorie_entreprise = "Résidentiel" if any(kw in specialites_str for kw in ['résidentiel', 'maison', 'habitation', 'residential']) else "Commercial"

                    prompt = f"""
Vous êtes un expert en soumission d'appels d'offres au Québec. Analysez objectivement l'appel d'offre fourni ci-dessous en vous basant UNIQUEMENT sur les informations suivantes :

### Informations sur votre entreprise :
- Nom : {user['nom_entreprise']}
- Spécialités : {', '.join(user.get('specialites', [])) or 'Non spécifiées'}
- Catégorie cible : {categorie_entreprise}
- Expériences antérieures : {len(projets_antecedents)} projets similaires (voir détails ci-dessous)
- Disponibilité : Vous avez besoin de 5 jours ouvrables minimum pour préparer une soumission.
- Contact client possible : Oui (vous avez un numéro de téléphone et un email).

### Projets antérieurs pertinents :
{chr(10).join([f"- {p['nom_projet']} ({p['montant']}$, {p['duree_jours']} jours)" for p in projets_antecedents[:3]]) or "Aucun projet antérieur fourni."}

### Contexte temporel :
- Date du jour : {today_str}
- Date minimale pour une visite de chantier : {visit_min} (au moins 3 jours ouvrables après aujourd'hui)
- Date limite minimale pour soumissionner : {deadline_min} (au moins 5 jours ouvrables après aujourd'hui)

### Appel d'offre à analyser :
{text}

### Instructions strictes :
1. NE FAITES AUCUNE HYPOTHÈSE. Si une information n'est pas dans le document, dites "non mentionné".
2. Vérifiez les critères suivants :
   - **Catégorie** : L'appel est-il résidentiel ou commercial ? Votre entreprise correspond-elle ?
   - **Visite de chantier** : Si une date de visite est mentionnée, est-elle ≥ {visit_min} ?
   - **Expérience similaire** : Le document décrit-il un type de projet que vous avez déjà réalisé ?
   - **Délai de soumission** : La date limite est-elle ≥ {deadline_min} ?
   - **Contact client** : Le document indique-t-il un contact ? (vous pouvez toujours appeler, mais vérifiez si requis)

3. Recommandation :
   - **GO** : Tous les critères de base sont remplis.
   - **PEUT-ÊTRE** : Manque seulement l'expérience similaire, mais autres critères OK.
   - **NO-GO** : Plus d'un critère manquant.

4. Structurez votre réponse ainsi :
   - **Recommandation** : [GO / PEUT-ÊTRE / NO-GO]
   - **Score** : [0–100]
   - **Vos forces pour cet appel d'offre** :
     - ...
   - **Points de vigilance** :
     - ...
   - **Actions recommandées** :
     - ...
   - **Justification concise** : ...

Utilisez un ton professionnel, courtois, et adressez-vous à l'utilisateur avec "vous". Ne mentionnez pas votre rôle d'IA.
"""

                    analysis_result = llm_manager.analyze(prompt, max_tokens=2000)
                    
                    if not analysis_result["success"]:
                        st.error(f"❌ {analysis_result['error']}")
                        st.stop()
                    
                    result = analysis_result["result"]
                    
                    st.markdown("### 📋 Résultat de l'analyse IA")
                    st.caption(f"🤖 Modèle utilisé: **{analysis_result['provider']}**")
                    st.markdown("---")
                    st.markdown(result)
                    
                    rec = "INCONNU"
                    if "GO" in result.upper() and "NO-GO" not in result.upper() and "NO GO" not in result.upper():
                        rec = "GO"
                    elif "NO-GO" in result.upper() or "NO GO" in result.upper():
                        rec = "NO-GO"
                    elif "PEUT-ÊTRE" in result.upper() or "MAYBE" in result.upper():
                        rec = "PEUT-ÊTRE"
                    
                    score = 0
                    score_match = re.search(r"Score\s*[:\-]?\s*(\d+)", result, re.IGNORECASE)
                    if score_match:
                        score = int(score_match.group(1))
                    
                    soumission_data = {
                        "numero_projet": numero_projet,
                        "nom_projet": nom_projet,
                        "document": uploaded_file,
                        "analyse_json": {
                            "raw_response": result,
                            "llm_used": analysis_result["provider"]
                        },
                        "recommendation": rec,
                        "score": score,
                        "statut": "qualifie" if rec == "GO" else "non_qualifie"
                    }
                    
                    soumission = save_soumission(user['id'], soumission_data)
                    if soumission:
                        st.success("✅ Analyse sauvegardée dans la base de données !")
                    else:
                        st.error("❌ Erreur lors de la sauvegarde")
                
                except Exception as e:
                    st.error(f"❌ Erreur: {str(e)}")
    
    with tab3:
        st.header("🏗️ Vos projets antérieurs")
        with st.expander("➕ Ajouter un projet"):
            with st.form("add_projet"):
                col1, col2 = st.columns(2)
                with col1:
                    nom_p = st.text_input("Nom du projet")
                    montant_p = st.number_input("Montant ($)", min_value=0)
                    duree_p = st.number_input("Durée (jours)", min_value=1)
                with col2:
                    specs_p = st.text_area("Spécifications")
                    doc_p = st.file_uploader("Document PDF", type=["pdf"])
                if st.form_submit_button("💾 Ajouter", use_container_width=False):
                    add_projet_antecedent({
                        "nom_projet": nom_p,
                        "montant": montant_p,
                        "duree_jours": duree_p,
                        "specifications": specs_p,
                        "document": doc_p
                    })
                    st.rerun()
        apply_supabase_auth()
        projets = supabase.table('projets_antecedents').select("*").eq('entreprise_id', user['id']).order('created_at', desc=True).execute()
        if not projets.data:
            st.info("📭 Aucun projet pour le moment")
        else:
            for projet in projets.data:
                with st.expander(f"🏗️ {projet['nom_projet']}"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**Montant:** ${projet['montant']:,.2f}")
                        st.write(f"**Durée:** {projet['duree_jours']} jours")
                    with col_b:
                        st.write(f"**Date:** {projet['created_at'][:10]}")
                        if projet.get('document_url'):
                            st.markdown(f"[📄 Voir document]({projet['document_url']})")
                    st.write(f"**Spécifications:** {projet['specifications']}")
    
    with tab4:
        st.header("👤 Vos informations")
        st.subheader("Entreprise")
        st.write(f"**Nom** : {user['nom_entreprise']}")
        st.write(f"**NEQ** : {user.get('numero_neq', 'N/A')}")
        st.write(f"**Licence RBQ** : {user.get('licence_rbq', 'N/A')}")
        st.write(f"**Spécialités** : {', '.join(user.get('specialites', []))}")
        st.write(f"**Adresse** : {user.get('adresse')}, {user.get('ville')}, {user.get('province')} {user.get('code_postal')}")
        
        st.subheader("Contact")
        st.write(f"**Nom** : {user['contact_nom']}")
        st.write(f"**Téléphone** : {user.get('contact_telephone', 'N/A')}")
        st.write(f"**Email** : {user['contact_email']}")
        
        if user.get('logo_url'):
            st.image(user['logo_url'], width=200)
        
        if st.button("✏️ Modifier le profil"):
            st.session_state.profile_completed = False
            st.rerun()import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import storage
import requests
from datetime import datetime, timedelta
import re

# --- CONFIGURATION ---
load_dotenv()
st.set_page_config(page_title="⚡ MOKAFAD - Solution Soumission IA", page_icon="⚡", layout="wide")

# --- STYLE BLEU CIEL ---
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] {
        background-color: #F0F8FF;
    }
    [data-testid="stSidebar"] {
        background-color: white;
        border-right: 2px solid #B0E0E6;
    }
    .stButton>button {
        background-color: #1E90FF !important;
        color: white !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.8rem !important;
        font-weight: 600 !important;
        width: auto !important;
        margin: 0.5rem auto !important;
        display: block !important;
        box-shadow: 0 2px 4px rgba(30, 144, 255, 0.3) !important;
    }
    .stButton>button:hover {
        background-color: #104E8B !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(30, 144, 255, 0.4) !important;
    }
    .stTabs [data-baseweb="tab"] {
        color: #104E8B !important;
        font-weight: 600 !important;
    }
    .stTabs [aria-selected="true"] {
        color: white !important;
        background-color: #1E90FF !important;
        border-radius: 8px 8px 0 0 !important;
    }
    h1, h2, h3 {
        color: #104E8B !important;
    }
    div[data-testid="stMetricValue"] {
        color: #104E8B !important;
    }
</style>
""", unsafe_allow_html=True)

# --- UTILITAIRES DATE ---
def is_business_day(date):
    return date.weekday() < 5  # Lundi=0, Dimanche=6

def add_business_days(start_date, days):
    current = start_date
    while days > 0:
        current += timedelta(days=1)
        if is_business_day(current):
            days -= 1
    return current

# --- VÉRIFICATION DES CLÉS ---
required_vars = ["SUPABASE_URL", "SUPABASE_ANON_KEY"]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    st.error(f"❌ Variables manquantes dans .env : {', '.join(missing)}")
    st.stop()

# --- CLIENT SUPABASE ---
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_ANON_KEY")
)

# ============================================
# 🆕 SYSTÈME DE FALLBACK GROQ → GEMINI
# ============================================

class LLMManager:
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        if os.getenv("GROQ_API_KEY"):
            self.providers.append({
                "name": "Groq LLaMA 3.3 70B",
                "api_key": os.getenv("GROQ_API_KEY"),
                "type": "groq"
            })
        if os.getenv("GEMINI_API_KEY"):
            try:
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                model = genai.GenerativeModel('gemini-2.0-flash-exp')
                self.providers.append({
                    "name": "Gemini 2.0 Flash",
                    "client": model,
                    "type": "gemini"
                })
            except Exception as e:
                st.warning(f"⚠️ Gemini non disponible: {str(e)[:100]}")
        if not self.providers:
            st.error("❌ Aucun LLM configuré ! Ajoutez GROQ_API_KEY ou GEMINI_API_KEY dans .env")
            st.stop()
    
    def analyze(self, prompt: str, max_tokens: int = 2000) -> dict:
        for provider in self.providers:
            try:
                if provider["type"] == "groq":
                    response = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {provider['api_key']}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0.3
                        },
                        timeout=30
                    )
                    response.raise_for_status()
                    return {
                        "success": True,
                        "result": response.json()["choices"][0]["message"]["content"],
                        "provider": provider["name"],
                        "error": None
                    }
                elif provider["type"] == "gemini":
                    response = provider["client"].generate_content(
                        prompt,
                        generation_config={"max_output_tokens": max_tokens, "temperature": 0.3}
                    )
                    return {
                        "success": True,
                        "result": response.text,
                        "provider": provider["name"],
                        "error": None
                    }
            except Exception:
                continue
        return {
            "success": False,
            "result": None,
            "provider": None,
            "error": "Tous les LLMs sont indisponibles. Réessayez plus tard."
        }

llm_manager = LLMManager()

# ============================================
# SESSION & FONCTIONS UTILITAIRES
# ============================================

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile_completed' not in st.session_state:
    st.session_state.profile_completed = False
if 'access_token' not in st.session_state:
    st.session_state.access_token = None

def apply_supabase_auth():
    """Applique le token JWT si disponible"""
    token = st.session_state.get('access_token')
    if token and isinstance(token, str) and token.strip():
        supabase.postgrest.auth(token)

# --- FONCTIONS BASE DE DONNÉES ---
def signup_user(data):
    try:
        supabase.auth.sign_up({
            "email": data["contact_email"], 
            "password": data["password"]
        })
        import time
        time.sleep(2)

        session = supabase.auth.sign_in_with_password({
            "email": data["contact_email"], 
            "password": data["password"]
        })

        if not session or not getattr(session, 'session', None) or not session.session.access_token:
            raise ValueError("Impossible de récupérer le token d'accès après connexion")

        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        entreprise_data = {
            "nom_entreprise": data["nom_entreprise"],
            "numero_neq": data["numero_neq"],
            "licence_rbq": data["licence_rbq"],
            "specialites": data["specialites"],
            "adresse": data["adresse"],
            "ville": data["ville"],
            "province": data["province"],
            "code_postal": data["code_postal"],
            "pays": data["pays"],
            "contact_nom": data["contact_nom"],
            "contact_telephone": data["contact_telephone"],
            "contact_email": data["contact_email"],
            "user_id": session.user.id
        }

        result = supabase.table('entreprises').insert(entreprise_data).execute()
        st.session_state.user = result.data[0]
        st.session_state.logged_in = True
        st.session_state.profile_completed = False
        return True

    except Exception as e:
        st.error(f"❌ Erreur inscription: {str(e)}")
        return False

def login_user(email, password):
    try:
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            return True
        return False
    except Exception as e:
        st.error(f"❌ Erreur connexion: {str(e)}")
        return False

def get_user_by_email(email):
    result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
    return result.data[0] if result.data else None

def update_entreprise_logo(entreprise_id, logo_url):
    apply_supabase_auth()
    supabase.table('entreprises').update({"logo_url": logo_url}).eq('id', entreprise_id).execute()

def add_projet_antecedent(projet_data):
    try:
        apply_supabase_auth()
        data = {
            "entreprise_id": st.session_state.user['id'],
            "nom_projet": projet_data["nom_projet"],
            "montant": projet_data["montant"],
            "duree_jours": projet_data["duree_jours"],
            "specifications": projet_data["specifications"]
        }
        if projet_data.get("document"):
            doc_url = storage.upload_document_projet(supabase, projet_data["document"])
            if doc_url:
                data["document_url"] = doc_url
        supabase.table('projets_antecedents').insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Erreur ajout projet: {str(e)}")
        return False

def save_soumission(entreprise_id, soumission_data):
    try:
        apply_supabase_auth()
        data_to_save = {
            "entreprise_id": entreprise_id,
            "numero_projet": soumission_data.get("numero_projet"),
            "nom_projet": soumission_data.get("nom_projet"),
            "analyse_json": soumission_data.get("analyse_json"),
            "recommendation": soumission_data.get("recommendation"),
            "score": soumission_data.get("score"),
            "statut": soumission_data.get("statut")
        }
        if soumission_data.get("document"):
            try:
                doc_url = storage.upload_soumission(supabase, soumission_data["document"])
                if doc_url:
                    data_to_save["document_url"] = doc_url
            except Exception:
                pass
        result = supabase.table('soumissions').insert(data_to_save).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Erreur sauvegarde soumission: {str(e)}")
        return None

# --- APPLICATION PRINCIPALE ---
st.title("⚡ MOKAFAD - Solution Soumission IA")

if st.session_state.logged_in and st.session_state.access_token:
    apply_supabase_auth()

# --- AUTHENTIFICATION ---
if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["🔐 Connexion", "📝 Inscription"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("📧 Email")
            password = st.text_input("🔒 Mot de passe", type="password")
            if st.form_submit_button("➡️ Se connecter", use_container_width=False):
                if login_user(email, password):
                    st.success("✅ Connecté !")
                    st.rerun()
    with tab2:
        signup_data = forms.signup_form()
        if signup_data:
            if get_user_by_email(signup_data["contact_email"]):
                st.error("❌ Cet email est déjà utilisé")
            elif signup_user(signup_data):
                st.success("✅ Compte créé ! Veuillez compléter votre profil.")
                st.rerun()

# --- PROFIL À COMPLÉTER ---
elif not st.session_state.profile_completed:
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    profile_data = forms.profile_completion_form(st.session_state.user)
    if profile_data:
        apply_supabase_auth()
        if profile_data["logo_file"]:
            try:
                logo_url = storage.upload_logo(supabase, profile_data["logo_file"])
                if logo_url:
                    update_entreprise_logo(st.session_state.user['id'], logo_url)
                    user_updated = supabase.table('entreprises').select("*").eq('id', st.session_state.user['id']).execute()
                    st.session_state.user = user_updated.data[0]
            except Exception as e:
                st.warning(f"⚠️ Logo non uploadé: {str(e)}")
        for projet in profile_data["projets"]:
            add_projet_antecedent(projet)
        st.session_state.profile_completed = True
        st.success("✅ Profil complété ! Redirection...")
        st.rerun()

# --- APPLICATION PRINCIPALE ---
else:
    user = st.session_state.user
    with st.sidebar:
        if user.get('logo_url'):
            st.image(user['logo_url'], width=150)
        st.write(f"👤 **{user['contact_nom']}**")
        st.write(f"🏢 **{user['nom_entreprise']}**")
        st.write(f"📍 {user['ville']}, {user['province']}")
        if st.button("🚪 Déconnexion", use_container_width=False):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()
    
    # Charger les projets antérieurs
    apply_supabase_auth()
    projets_response = supabase.table('projets_antecedents').select("*").eq('entreprise_id', user['id']).execute()
    projets_antecedents = projets_response.data or []

    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Tableau de bord", 
        "🔍 Nouvelle analyse", 
        "🏗️ Projets antérieurs", 
        "👤 Mon profil"
    ])
    
    with tab1:
        st.header("📊 Tableau de bord")
        apply_supabase_auth()
        col1, col2, col3 = st.columns(3)
        with col1:
            projets = supabase.table('projets_antecedents').select("id", count="exact").eq('entreprise_id', user['id']).execute()
            st.metric("🏗️ Projets réalisés", projets.count)
        with col2:
            soumissions = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).execute()
            st.metric("📄 Soumissions analysées", soumissions.count)
        with col3:
            qualifies = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).eq('statut', 'qualifie').execute()
            st.metric("✅ Qualifiées", qualifies.count)
        st.markdown("---")
        st.subheader("📈 Dernières analyses")
        recent = supabase.table('soumissions').select("*").eq('entreprise_id', user['id']).order('created_at', desc=True).limit(5).execute()
        if recent.data:
            for item in recent.data:
                with st.expander(f"📄 {item.get('nom_projet', 'Sans nom')} - {item['created_at'][:10]}"):
                    st.write(f"**Statut:** {item['statut']}")
                    st.write(f"**Recommandation:** {item.get('recommendation', 'N/A')}")
                    st.write(f"**Score:** {item.get('score', 'N/A')}")
                    if item.get('analyse_json') and isinstance(item['analyse_json'], dict):
                        llm_used = item['analyse_json'].get('llm_used', 'N/A')
                        st.write(f"**Modèle IA:** {llm_used}")
        else:
            st.info("📭 Aucune analyse récente")
    
    with tab2:
        st.header("🔍 Lancer une préqualification")
        with st.form("analyse_form"):
            numero_projet = st.text_input("🔢 Numéro du projet")
            nom_projet = st.text_input("📋 Nom du projet")
            uploaded_file = st.file_uploader("📄 PDF Appel d'offre", type=['pdf'])
            submit = st.form_submit_button("🚀 Lancer l'analyse", use_container_width=False)
        
        if submit and uploaded_file:
            with st.spinner("🤖 Analyse IA en cours..."):
                try:
                    reader = PdfReader(uploaded_file)
                    text = " ".join([page.extract_text() or "" for page in reader.pages])[:8000]
                    
                    today = datetime.today()
                    deadline_min = add_business_days(today, 5).strftime("%Y-%m-%d")
                    visit_min = add_business_days(today, 3).strftime("%Y-%m-%d")
                    today_str = today.strftime("%Y-%m-%d")

                    specialites_str = " ".join(user.get('specialites', [])).lower()
                    categorie_entreprise = "Résidentiel" if any(kw in specialites_str for kw in ['résidentiel', 'maison', 'habitation', 'residential']) else "Commercial"

                    prompt = f"""
Vous êtes un expert en soumission d'appels d'offres au Québec. Analysez objectivement l'appel d'offre fourni ci-dessous en vous basant UNIQUEMENT sur les informations suivantes :

### Informations sur votre entreprise :
- Nom : {user['nom_entreprise']}
- Spécialités : {', '.join(user.get('specialites', [])) or 'Non spécifiées'}
- Catégorie cible : {categorie_entreprise}
- Expériences antérieures : {len(projets_antecedents)} projets similaires
- Disponibilité : Vous avez besoin de 5 jours ouvrables minimum pour préparer une soumission.
- Contact client possible : Oui.

### Projets antérieurs pertinents :
{chr(10).join([f"- {p['nom_projet']} ({p['montant']}$, {p['duree_jours']} jours)" for p in projets_antecedents[:3]]) or "Aucun projet antérieur fourni."}

### Contexte temporel :
- Date du jour : {today_str}
- Date minimale visite : {visit_min}
- Date limite soumission : {deadline_min}

### Appel d'offre :
{text}

### Instructions :
1. NE FAITES AUCUNE HYPOTHÈSE. Si info absente → "non mentionné".
2. Vérifiez :
   - Catégorie correspondante ?
   - Visite ≥ {visit_min} ?
   - Expérience similaire ?
   - Délai ≥ {deadline_min} ?
   - Contact client requis ?
3. Recommandation :
   - GO : tous critères OK
   - PEUT-ÊTRE : manque expérience seulement
   - NO-GO : autre cas
4. Structure :
   - **Recommandation** : [...]
   - **Score** : [...]
   - **Vos forces** : [...]
   - **Points de vigilance** : [...]
   - **Actions recommandées** : [...]
   - **Justification** : [...]

Utilisez "vous", ton courtois, pas d'IA.
"""

                    analysis_result = llm_manager.analyze(prompt, max_tokens=2000)
                    if not analysis_result["success"]:
                        st.error(f"❌ {analysis_result['error']}")
                        st.stop()
                    
                    result = analysis_result["result"]
                    st.markdown("### 📋 Résultat de l'analyse IA")
                    st.caption(f"🤖 Modèle utilisé: **{analysis_result['provider']}**")
                    st.markdown("---")
                    st.markdown(result)
                    
                    rec = "INCONNU"
                    if "GO" in result.upper() and "NO-GO" not in result.upper() and "NO GO" not in result.upper():
                        rec = "GO"
                    elif "NO-GO" in result.upper() or "NO GO" in result.upper():
                        rec = "NO-GO"
                    elif "PEUT-ÊTRE" in result.upper() or "MAYBE" in result.upper():
                        rec = "PEUT-ÊTRE"
                    
                    score = 0
                    score_match = re.search(r"Score\s*[:\-]?\s*(\d+)", result, re.IGNORECASE)
                    if score_match:
                        score = int(score_match.group(1))
                    
                    soumission_data = {
                        "numero_projet": numero_projet,
                        "nom_projet": nom_projet,
                        "document": uploaded_file,
                        "analyse_json": {"raw_response": result, "llm_used": analysis_result["provider"]},
                        "recommendation": rec,
                        "score": score,
                        "statut": "qualifie" if rec == "GO" else "non_qualifie"
                    }
                    
                    soumission = save_soumission(user['id'], soumission_data)
                    if soumission:
                        st.success("✅ Analyse sauvegardée !")
                    else:
                        st.error("❌ Erreur sauvegarde")
                
                except Exception as e:
                    st.error(f"❌ Erreur: {str(e)}")
    
    with tab3:
        st.header("🏗️ Vos projets antérieurs")
        with st.expander("➕ Ajouter un projet"):
            with st.form("add_projet"):
                col1, col2 = st.columns(2)
                with col1:
                    nom_p = st.text_input("Nom du projet")
                    montant_p = st.number_input("Montant ($)", min_value=0)
                    duree_p = st.number_input("Durée (jours)", min_value=1)
                with col2:
                    specs_p = st.text_area("Spécifications")
                    doc_p = st.file_uploader("Document PDF", type=["pdf"])
                if st.form_submit_button("💾 Ajouter", use_container_width=False):
                    add_projet_antecedent({
                        "nom_projet": nom_p,
                        "montant": montant_p,
                        "duree_jours": duree_p,
                        "specifications": specs_p,
                        "document": doc_p
                    })
                    st.rerun()
        apply_supabase_auth()
        projets = supabase.table('projets_antecedents').select("*").eq('entreprise_id', user['id']).order('created_at', desc=True).execute()
        if not projets.data:
            st.info("📭 Aucun projet pour le moment")
        else:
            for projet in projets.data:
                with st.expander(f"🏗️ {projet['nom_projet']}"):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.write(f"**Montant:** ${projet['montant']:,.2f}")
                        st.write(f"**Durée:** {projet['duree_jours']} jours")
                    with col_b:
                        st.write(f"**Date:** {projet['created_at'][:10]}")
                        if projet.get('document_url'):
                            st.markdown(f"[📄 Voir document]({projet['document_url']})")
                    st.write(f"**Spécifications:** {projet['specifications']}")
    
    with tab4:
        st.header("👤 Vos informations")
        st.subheader("Entreprise")
        st.write(f"**Nom** : {user['nom_entreprise']}")
        st.write(f"**NEQ** : {user.get('numero_neq', 'N/A')}")
        st.write(f"**Licence RBQ** : {user.get('licence_rbq', 'N/A')}")
        st.write(f"**Spécialités** : {', '.join(user.get('specialites', []))}")
        st.write(f"**Adresse** : {user.get('adresse')}, {user.get('ville')}, {user.get('province')} {user.get('code_postal')}")
        
        st.subheader("Contact")
        st.write(f"**Nom** : {user['contact_nom']}")
        st.write(f"**Téléphone** : {user.get('contact_telephone', 'N/A')}")
        st.write(f"**Email** : {user['contact_email']}")
        
        if user.get('logo_url'):
            st.image(user['logo_url'], width=200)
        
        if st.button("✏️ Modifier le profil"):
            st.session_state.profile_completed = False
            st.rerun()
