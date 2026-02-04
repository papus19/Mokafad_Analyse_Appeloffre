import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import storage
import anthropic  # pip install anthropic
import requests  # Pour Groq/Together AI

# --- CONFIGURATION ---
load_dotenv()
st.set_page_config(page_title="⚡ MOKAFAD - Solution Soumission IA", page_icon="⚡", layout="wide")

# --- STYLE BLEU CIEL (inchangé) ---
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

# --- CLIENTS ---
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_ANON_KEY")
)

# ============================================
# 🆕 SYSTÈME DE FALLBACK ENTRE LLMs
# ============================================

class LLMManager:
    """Gère les appels aux différents LLMs avec fallback automatique"""
    
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        """Initialise les LLMs disponibles dans l'ordre de priorité"""
        
        # 1️⃣ GEMINI (priorité 1)
        if os.getenv("GEMINI_API_KEY"):
            try:
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                model = genai.GenerativeModel('gemini-2.0-flash-exp')
                # Test rapide
                model.generate_content("test", generation_config={"max_output_tokens": 5})
                self.providers.append({
                    "name": "Gemini 2.0 Flash",
                    "client": model,
                    "type": "gemini"
                })
            except Exception as e:
                st.warning(f"⚠️ Gemini indisponible: {str(e)[:100]}")
        
        # 2️⃣ CLAUDE (priorité 2)
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
                self.providers.append({
                    "name": "Claude Haiku",
                    "client": client,
                    "type": "claude"
                })
            except Exception as e:
                st.warning(f"⚠️ Claude indisponible: {str(e)[:100]}")
        
        # 3️⃣ GROQ (priorité 3 - gratuit et rapide)
        if os.getenv("GROQ_API_KEY"):
            self.providers.append({
                "name": "Groq LLaMA",
                "api_key": os.getenv("GROQ_API_KEY"),
                "type": "groq"
            })
        
        # 4️⃣ TOGETHER AI (priorité 4)
        if os.getenv("TOGETHER_API_KEY"):
            self.providers.append({
                "name": "Together AI",
                "api_key": os.getenv("TOGETHER_API_KEY"),
                "type": "together"
            })
        
        if not self.providers:
            st.error("❌ Aucun LLM configuré ! Ajoutez au moins une clé API dans .env")
            st.stop()
    
    def analyze(self, prompt: str, max_tokens: int = 2000) -> dict:
        """
        Analyse avec fallback automatique
        Retourne: {"success": bool, "result": str, "provider": str, "error": str}
        """
        
        for i, provider in enumerate(self.providers):
            try:
                st.info(f"🤖 Tentative avec {provider['name']} ({i+1}/{len(self.providers)})")
                
                if provider["type"] == "gemini":
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
                
                elif provider["type"] == "claude":
                    message = provider["client"].messages.create(
                        model="claude-3-5-haiku-20241022",
                        max_tokens=max_tokens,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    return {
                        "success": True,
                        "result": message.content[0].text,
                        "provider": provider["name"],
                        "error": None
                    }
                
                elif provider["type"] == "groq":
                    response = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {provider['api_key']}"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0.3
                        }
                    )
                    response.raise_for_status()
                    return {
                        "success": True,
                        "result": response.json()["choices"][0]["message"]["content"],
                        "provider": provider["name"],
                        "error": None
                    }
                
                elif provider["type"] == "together":
                    response = requests.post(
                        "https://api.together.xyz/v1/chat/completions",
                        headers={"Authorization": f"Bearer {provider['api_key']}"},
                        json={
                            "model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0.3
                        }
                    )
                    response.raise_for_status()
                    return {
                        "success": True,
                        "result": response.json()["choices"][0]["message"]["content"],
                        "provider": provider["name"],
                        "error": None
                    }
            
            except Exception as e:
                error_msg = str(e)
                st.warning(f"❌ {provider['name']} a échoué: {error_msg[:150]}")
                
                # Si c'est le dernier provider, on retourne l'erreur
                if i == len(self.providers) - 1:
                    return {
                        "success": False,
                        "result": None,
                        "provider": None,
                        "error": f"Tous les LLMs ont échoué. Dernière erreur: {error_msg}"
                    }
                
                # Sinon on continue avec le prochain
                continue
        
        return {
            "success": False,
            "result": None,
            "provider": None,
            "error": "Aucun LLM disponible"
        }

# Initialiser le gestionnaire
llm_manager = LLMManager()

# ============================================
# FIN SYSTÈME DE FALLBACK
# ============================================

# Session (inchangé)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile_completed' not in st.session_state:
    st.session_state.profile_completed = False

# --- FONCTIONS BASE DE DONNÉES (inchangées) ---
def signup_user(data):
    try:
        user_auth = supabase.auth.sign_up({
            "email": data["contact_email"], 
            "password": data["password"]
        })
        import time
        time.sleep(2)
        session = supabase.auth.sign_in_with_password({
            "email": data["contact_email"], 
            "password": data["password"]
        })
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
        st.error(f"❌ Erreur: {str(e)}")
        return False

def login_user(email, password):
    try:
        session = supabase.auth.sign_in_with_password({"email": email, "password": password})
        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            return True
        return False
    except Exception as e:
        st.error(f"❌ Erreur: {str(e)}")
        return False

def get_user_by_email(email):
    result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
    return result.data[0] if result.data else None

def update_entreprise_logo(entreprise_id, logo_url):
    supabase.table('entreprises').update({"logo_url": logo_url}).eq('id', entreprise_id).execute()

def add_projet_antecedent(projet_data):
    try:
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

# --- APPLICATION ---
st.title("⚡ MOKAFAD - Solution Soumission IA")

# Afficher les LLMs disponibles dans la sidebar
with st.sidebar:
    st.markdown("### 🤖 LLMs configurés")
    for i, provider in enumerate(llm_manager.providers, 1):
        st.success(f"{i}. {provider['name']}")

# --- AUTHENTIFICATION (inchangé) ---
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

# --- PROFIL À COMPLÉTER (inchangé) ---
elif not st.session_state.profile_completed:
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    profile_data = forms.profile_completion_form(st.session_state.user)
    if profile_data:
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
            st.session_state.clear()
            st.rerun()
    
    tab1, tab2, tab3 = st.tabs(["📋 Tableau de bord", "🔍 Nouvelle analyse", "🏗️ Projets antérieurs"])
    
    with tab1:
        st.header("📊 Tableau de bord")
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
                    
                    # 🆕 UTILISATION DU SYSTÈME DE FALLBACK
                    analysis_result = llm_manager.analyze(prompt, max_tokens=2000)
                    
                    if not analysis_result["success"]:
                        st.error(f"❌ {analysis_result['error']}")
                        st.stop()
                    
                    # Afficher quel LLM a été utilisé
                    st.success(f"✅ Analyse réussie avec **{analysis_result['provider']}**")
                    
                    result = analysis_result["result"]
                    
                    st.markdown("### 📋 Résultat de l'analyse IA")
                    st.markdown("---")
                    st.markdown(result)
                    
                    # Extraction de la recommandation
                    rec = "INCONNU"
                    if "GO" in result.upper() and "NO-GO" not in result.upper() and "NO GO" not in result.upper():
                        rec = "GO"
                    elif "NO-GO" in result.upper() or "NO GO" in result.upper():
                        rec = "NO-GO"
                    elif "PEUT-ÊTRE" in result.upper() or "MAYBE" in result.upper():
                        rec = "PEUT-ÊTRE"
                    
                    # Sauvegarde
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
