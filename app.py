import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import storage
import requests

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
    """Gère les appels Groq puis Gemini en fallback"""
    
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        """Initialise Groq en priorité, puis Gemini"""
        
        # 1️⃣ GROQ (priorité 1 - gratuit et rapide)
        if os.getenv("GROQ_API_KEY"):
            self.providers.append({
                "name": "Groq LLaMA 3.3 70B",
                "api_key": os.getenv("GROQ_API_KEY"),
                "type": "groq"
            })
        
        # 2️⃣ GEMINI (priorité 2 - fallback)
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
        """
        Analyse avec fallback automatique Groq → Gemini
        Retourne: {"success": bool, "result": str, "provider": str, "error": str}
        """
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
            
            except Exception as e:
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
    """Applique le token s'il existe, sinon désactive l'auth (sûr pour les SELECT publics)"""
    token = st.session_state.get('access_token')
    if token and isinstance(token, str) and token.strip():
        supabase.postgrest.auth(token)
    else:
        supabase.postgrest.auth(None)  # explicite : pas d'auth

def clear_supabase_auth():
    """Supprime l'authentification du client"""
    supabase.postgrest.auth(None)

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

        # 🔍 Validation stricte du token
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
        clear_supabase_auth()
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
        clear_supabase_auth()
        return False

def get_user_by_email(email):
    apply_supabase_auth()  # au cas où
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

# Restaurer l'auth si reload
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
            supabase.auth.sign_out()
            clear_supabase_auth()
            st.session_state.clear()
            st.rerun()
    
    tab1, tab2, tab3 = st.tabs(["📋 Tableau de bord", "🔍 Nouvelle analyse", "🏗️ Projets antérieurs"])
    
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
                    
                    context = f"""
                    Entreprise: {user['nom_entreprise']}
                    Spécialités: {', '.join(user.get('specialites', []))}
                    NEQ: {user.get('numero_neq', 'N/A')}
                    Licence RBQ: {user.get('licence_rbq', 'N/A')}
                    Adresse: {user.get('adresse', '')}, {user.get('ville', '')}, {user.get('province', '')}
                    """
                    
                    prompt = f"""
                    {context}
                    Analysez cet appel d'offre et donnez:
                    1. Recommandation: GO / NO-GO / PEUT-ÊTRE
                    2. Score sur 100
                    3. Points forts (liste)
                    4. Points faibles (liste)
                    5. Actions recommandées (liste)
                    6. Justification détaillée
                    Document:
                    {text}
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
                    
                    soumission_data = {
                        "numero_projet": numero_projet,
                        "nom_projet": nom_projet,
                        "document": uploaded_file,
                        "analyse_json": {
                            "raw_response": result,
                            "llm_used": analysis_result["provider"]
                        },
                        "recommendation": rec,
                        "score": 0,
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
