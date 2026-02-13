import streamlit as st
import os
from dotenv import load_dotenv
import google.generativeai as genai
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import requests
from datetime import datetime, timedelta
import re
import base64

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
    """Vérifie si une date est un jour ouvrable (lundi-vendredi)"""
    return date.weekday() < 5

def add_business_days(start_date, days):
    """Ajoute un nombre de jours ouvrables à une date"""
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
try:
    supabase: Client = create_client(
        os.getenv("SUPABASE_URL"), 
        os.getenv("SUPABASE_ANON_KEY")
    )
    
    # Client admin pour contourner RLS lors de l'inscription (optionnel)
    # Si SUPABASE_SERVICE_ROLE_KEY existe dans .env
    supabase_admin = None
    if os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        try:
            supabase_admin = create_client(
                os.getenv("SUPABASE_URL"),
                os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            )
        except Exception as e:
            st.warning(f"⚠️ Service role non disponible : {str(e)[:100]}")
            
except Exception as e:
    st.error(f"❌ Erreur de connexion à Supabase : {str(e)}")
    st.stop()

# ============================================
# SYSTÈME DE FALLBACK: GEMINI EN PREMIER
# ============================================

class LLMManager:
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        """Initialise les fournisseurs LLM avec Gemini en priorité"""
        # GEMINI EN PREMIER
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
                st.warning(f"⚠️ Gemini non disponible : {str(e)[:100]}")
        
        # Groq en second
        if os.getenv("GROQ_API_KEY"):
            self.providers.append({
                "name": "Groq LLaMA 3.3 70B",
                "api_key": os.getenv("GROQ_API_KEY"),
                "type": "groq"
            })
        
        if not self.providers:
            st.error("❌ Aucun LLM configuré ! Ajoutez GEMINI_API_KEY ou GROQ_API_KEY dans .env")
            st.stop()
    
    def analyze(self, prompt: str, max_tokens: int = 2000) -> dict:
        """Analyse un prompt avec fallback automatique entre les LLMs"""
        last_error = None
        
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
            except requests.exceptions.Timeout:
                last_error = f"Le service {provider['name']} a mis trop de temps à répondre"
                continue
            except requests.exceptions.ConnectionError:
                last_error = f"Impossible de se connecter au service {provider['name']}"
                continue
            except Exception as e:
                last_error = f"Erreur avec {provider['name']}: {str(e)[:100]}"
                continue
        
        return {
            "success": False,
            "result": None,
            "provider": None,
            "error": last_error or "Tous les services d'IA sont indisponibles. Veuillez réessayer plus tard."
        }

llm_manager = LLMManager()

# ============================================
# SESSION & FONCTIONS UTILITAIRES
# ============================================

# Initialisation de la session
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile_completed' not in st.session_state:
    st.session_state.profile_completed = False
if 'access_token' not in st.session_state:
    st.session_state.access_token = None
if 'show_login_tab' not in st.session_state:
    st.session_state.show_login_tab = True
if 'default_tab' not in st.session_state:
    st.session_state.default_tab = 0  # 0 = Tableau de bord par défaut

def apply_supabase_auth():
    """Applique le token d'authentification aux requêtes Supabase"""
    try:
        token = st.session_state.get('access_token')
        if token and isinstance(token, str) and token.strip():
            supabase.postgrest.auth(token)
    except Exception as e:
        st.warning(f"⚠️ Erreur d'authentification : {str(e)}")

# --- FONCTIONS BASE DE DONNÉES ---

def signup_user(data):
    """Inscription d'un nouvel utilisateur"""
    try:
        # Validation obligatoire NEQ et RBQ
        if not data.get("numero_neq") or not data.get("licence_rbq"):
            st.error("❌ Le NEQ et la licence RBQ sont obligatoires")
            return False
        
        # Validation email
        if not data.get("contact_email") or "@" not in data.get("contact_email", ""):
            st.error("❌ L'adresse courriel est invalide")
            return False
        
        # Validation mot de passe
        if not data.get("password") or len(data.get("password", "")) < 6:
            st.error("❌ Le mot de passe doit contenir au moins 6 caractères")
            return False
        
        # Vérifier si l'utilisateur existe déjà
        try:
            existing_user = get_user_by_email(data["contact_email"])
            if existing_user:
                st.error("❌ Cette adresse courriel est déjà utilisée. Veuillez vous connecter.")
                return False
        except:
            pass
            
        # Inscription avec auto-confirm si disponible
        try:
            response = supabase.auth.sign_up({
                "email": data["contact_email"], 
                "password": data["password"],
                "options": {
                    "data": {
                        "nom_entreprise": data["nom_entreprise"],
                        "numero_neq": data["numero_neq"],
                        "licence_rbq": data["licence_rbq"]
                    }
                }
            })
        except Exception as auth_error:
            error_msg = str(auth_error).lower()
            if "rate limit" in error_msg:
                st.error("⏱️ Trop de tentatives d'inscription. Veuillez patienter 60 secondes.")
                st.info("💡 Si vous avez déjà un compte, utilisez l'onglet Connexion.")
                return False
            else:
                raise auth_error
        
        # Vérifier que l'utilisateur a été créé
        if not response.user or not response.user.id:
            st.error("❌ Erreur lors de la création du compte. Veuillez réessayer.")
            return False
        
        user_id = response.user.id
        
        # Préparer les données de l'entreprise
        entreprise_data = {
            "nom_entreprise": data["nom_entreprise"],
            "numero_neq": data["numero_neq"],
            "licence_rbq": data["licence_rbq"],
            "specialites": data.get("specialites", []),
            "adresse": data.get("adresse", ""),
            "ville": data.get("ville", ""),
            "province": data.get("province", ""),
            "code_postal": data.get("code_postal", ""),
            "pays": data.get("pays", "Canada"),
            "contact_nom": data.get("contact_nom", ""),
            "contact_telephone": data.get("contact_telephone", ""),
            "contact_email": data["contact_email"],
            "user_id": user_id
        }

        # STRATÉGIE 1: Utiliser le token de session si disponible
        insertion_success = False
        
        if response.session and response.session.access_token:
            try:
                # Créer un client temporaire avec le token de session
                from supabase import create_client
                temp_client = create_client(
                    os.getenv("SUPABASE_URL"),
                    os.getenv("SUPABASE_ANON_KEY")
                )
                temp_client.postgrest.auth(response.session.access_token)
                
                result = temp_client.table('entreprises').insert(entreprise_data).execute()
                
                if result.data and len(result.data) > 0:
                    insertion_success = True
                    # Déconnexion immédiate
                    try:
                        supabase.auth.sign_out()
                    except:
                        pass
            except Exception as e:
                st.warning(f"⚠️ Tentative 1 échouée : {str(e)[:100]}")
        
        # STRATÉGIE 2: Utiliser service_role si disponible et stratégie 1 échouée
        if not insertion_success and supabase_admin:
            try:
                result = supabase_admin.table('entreprises').insert(entreprise_data).execute()
                if result.data and len(result.data) > 0:
                    insertion_success = True
            except Exception as e:
                st.warning(f"⚠️ Tentative 2 échouée : {str(e)[:100]}")
        
        # STRATÉGIE 3: Dernière tentative avec client principal
        if not insertion_success:
            try:
                result = supabase.table('entreprises').insert(entreprise_data).execute()
                if result.data and len(result.data) > 0:
                    insertion_success = True
            except Exception as e:
                st.error(f"❌ Toutes les tentatives d'insertion ont échoué")
                st.info("💡 Votre compte a été créé mais le profil n'a pas pu être enregistré.")
                st.info("🔧 Veuillez contacter le support avec ce message d'erreur :")
                st.code(str(e))
        
        return insertion_success

    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg:
            st.error("⏱️ Trop de tentatives. Veuillez patienter 60 secondes.")
            st.info("💡 Si vous avez déjà un compte, utilisez l'onglet Connexion.")
        elif "already registered" in error_msg or "already exists" in error_msg:
            st.error("❌ Cette adresse courriel est déjà utilisée. Veuillez vous connecter.")
        elif "invalid email" in error_msg:
            st.error("❌ L'adresse courriel est invalide")
        elif "password" in error_msg:
            st.error("❌ Le mot de passe ne respecte pas les critères requis")
        elif "row-level security" in error_msg or "policy" in error_msg:
            st.error("❌ Erreur de permissions de la base de données")
            st.info("💡 Contactez l'administrateur pour corriger les policies RLS")
            st.code("Erreur RLS - Exécutez le script fix_all_rls_policies.sql")
        else:
            st.error(f"❌ Erreur lors de l'inscription : {str(e)}")
        return False

def login_user(email, password):
    """Connexion d'un utilisateur"""
    try:
        if not email or not password:
            st.error("❌ Veuillez entrer votre courriel et mot de passe")
            return False
        
        session = supabase.auth.sign_in_with_password({
            "email": email, 
            "password": password
        })
        
        if not session or not session.session or not session.session.access_token:
            st.error("❌ Erreur de connexion. Veuillez vérifier vos identifiants.")
            return False
        
        st.session_state.access_token = session.session.access_token
        apply_supabase_auth()

        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        
        if result.data and len(result.data) > 0:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            # Profil complété si logo existe
            st.session_state.profile_completed = bool(st.session_state.user.get('logo'))
            # Forcer l'affichage du tableau de bord
            if 'active_tab' not in st.session_state:
                st.session_state.active_tab = 0  # Tab 0 = Tableau de bord
            return True
        else:
            st.error("❌ Impossible de récupérer les informations de votre profil")
            return False
            
    except Exception as e:
        error_msg = str(e).lower()
        if "email not confirmed" in error_msg or "email_not_confirmed" in error_msg:
            st.error("📧 Votre courriel n'a pas encore été validé. Veuillez cliquer sur le lien dans le courriel de confirmation que nous vous avons envoyé. Pensez à vérifier dans vos courriels indésirables (spam).")
        elif "invalid login" in error_msg or "invalid credentials" in error_msg:
            st.error("❌ Courriel ou mot de passe incorrect")
        elif "too many requests" in error_msg or "rate limit" in error_msg:
            st.error("⏱️ Trop de tentatives de connexion. Veuillez patienter quelques minutes.")
        else:
            st.error(f"❌ Erreur de connexion : {str(e)}")
        return False

def get_user_by_email(email):
    """Récupère un utilisateur par son email"""
    try:
        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        return result.data[0] if result.data and len(result.data) > 0 else None
    except Exception as e:
        st.warning(f"⚠️ Erreur lors de la vérification du courriel : {str(e)}")
        return None

def add_projet_antecedent(projet_data):
    """Ajoute un projet antérieur"""
    try:
        apply_supabase_auth()
        
        # Validation des données
        if not projet_data.get("nom_projet"):
            st.error("❌ Le nom du projet est obligatoire")
            return False
        
        data = {
            "entreprise_id": st.session_state.user['id'],
            "nom_projet": projet_data["nom_projet"],
            "montant": projet_data.get("montant", 0),
            "duree_jours": projet_data.get("duree_jours", 0),
            "specifications": projet_data.get("specifications", "")
        }
        
        # Upload document si présent
        if projet_data.get("document"):
            try:
                import storage
                doc_url = storage.upload_document_projet(supabase, projet_data["document"])
                if doc_url:
                    data["document_url"] = doc_url
            except ImportError:
                st.warning("⚠️ Module storage non disponible. Le document ne sera pas uploadé.")
            except Exception as e:
                st.warning(f"⚠️ Erreur lors de l'upload du document : {str(e)}")
        
        result = supabase.table('projets_antecedents').insert(data).execute()
        
        if result.data and len(result.data) > 0:
            st.success("✅ Projet ajouté avec succès")
            return True
        else:
            st.error("❌ Erreur lors de l'ajout du projet")
            return False
            
    except Exception as e:
        st.error(f"❌ Erreur lors de l'ajout du projet : {str(e)}")
        return False

def save_soumission(entreprise_id, soumission_data):
    """Sauvegarde une analyse de soumission"""
    try:
        apply_supabase_auth()
        
        data_to_save = {
            "entreprise_id": entreprise_id,
            "numero_projet": soumission_data.get("numero_projet", ""),
            "nom_projet": soumission_data.get("nom_projet", ""),
            "analyse_json": soumission_data.get("analyse_json", {}),
            "recommendation": soumission_data.get("recommendation", "INCONNU"),
            "score": soumission_data.get("score", 0),
            "statut": soumission_data.get("statut", "en_attente")
        }
        
        # Upload document si présent
        if soumission_data.get("document"):
            try:
                import storage
                doc_url = storage.upload_soumission(supabase, soumission_data["document"])
                if doc_url:
                    data_to_save["document_url"] = doc_url
            except ImportError:
                pass
            except Exception as e:
                st.warning(f"⚠️ Document non uploadé : {str(e)}")
        
        result = supabase.table('soumissions').insert(data_to_save).execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        else:
            return None
            
    except Exception as e:
        st.error(f"❌ Erreur lors de la sauvegarde : {str(e)}")
        return None

# --- APPLICATION PRINCIPALE ---

# Appliquer l'authentification si connecté
if st.session_state.logged_in and st.session_state.access_token:
    apply_supabase_auth()

# --- AUTHENTIFICATION ---
if not st.session_state.logged_in:
    # Afficher les onglets d'authentification
    tab1, tab2 = st.tabs(["🔐 Connexion", "📝 Inscription"])
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("📧 Courriel")
            password = st.text_input("🔒 Mot de passe", type="password")
            submit = st.form_submit_button("➡️ Se connecter", use_container_width=False)
            
            if submit:
                if login_user(email, password):
                    st.success("✅ Connexion réussie !")
                    st.rerun()
    
    with tab2:
        try:
            signup_data = forms.signup_form()
            
            if signup_data:
                # Validation obligatoire NEQ et RBQ AVANT soumission
                if not signup_data.get("numero_neq") or not signup_data.get("licence_rbq"):
                    st.error("❌ Le NEQ et la licence RBQ sont obligatoires pour créer un compte")
                elif get_user_by_email(signup_data["contact_email"]):
                    st.error("❌ Cette adresse courriel est déjà utilisée")
                elif signup_user(signup_data):
                    st.success("✅ Compte créé avec succès !")
                    st.info("📧 Un courriel de validation a été envoyé à **{}**. Pensez à vérifier dans vos courriels indésirables (spam).".format(signup_data["contact_email"]))
                    st.info("🔐 Vous pouvez maintenant vous connecter avec vos identifiants.")
                    # Basculer vers l'onglet de connexion
                    st.session_state.show_login_tab = True
                    # Petit délai pour que l'utilisateur voie le message
                    import time
                    time.sleep(2)
                    # Recharger pour effacer le formulaire
                    st.rerun()
        except Exception as e:
            st.error(f"❌ Erreur lors de l'inscription : {str(e)}")

# --- PROFIL À COMPLÉTER ---
elif not st.session_state.profile_completed:
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    
    try:
        profile_data = forms.profile_completion_form(st.session_state.user)
        
        if profile_data:
            apply_supabase_auth()
            
            # STOCKAGE DU LOGO EN BASE64
            logo_updated = False
            if profile_data.get("logo_file"):
                try:
                    logo_bytes = profile_data["logo_file"].read()
                    logo_base64 = base64.b64encode(logo_bytes).decode('utf-8')
                    
                    supabase.table('entreprises').update({
                        "logo": logo_base64
                    }).eq('id', st.session_state.user['id']).execute()
                    
                    # Recharger l'utilisateur
                    user_updated = supabase.table('entreprises').select("*").eq(
                        'id', st.session_state.user['id']
                    ).execute()
                    
                    if user_updated.data and len(user_updated.data) > 0:
                        st.session_state.user = user_updated.data[0]
                        logo_updated = True
                        st.success("✅ Logo uploadé avec succès !")
                        
                except Exception as e:
                    st.warning(f"⚠️ Erreur lors de l'enregistrement du logo : {str(e)}")
            
            # Ajout des projets antérieurs
            if profile_data.get("projets"):
                projets_added = 0
                for projet in profile_data["projets"]:
                    if add_projet_antecedent(projet):
                        projets_added += 1
                if projets_added > 0:
                    st.success(f"✅ {projets_added} projet(s) ajouté(s) avec succès !")
            
            st.session_state.profile_completed = True
            st.session_state.default_tab = 0  # Forcer ouverture sur tableau de bord
            st.success("✅ Profil complété ! Redirection vers le tableau de bord...")
            import time
            time.sleep(1.5)
            st.rerun()
            
    except Exception as e:
        st.error(f"❌ Erreur lors de la complétion du profil : {str(e)}")

# --- APPLICATION PRINCIPALE ---
else:
    user = st.session_state.user
    
    # SIDEBAR
    with st.sidebar:
        # Logo MOKAFAD en haut
        st.markdown(
            f'<div style="text-align: center; margin-bottom: 20px;"><img src="{MOKAFAD_LOGO_URL}" width="80"></div>',
            unsafe_allow_html=True
        )
        
        # AFFICHAGE DU LOGO DE L'ENTREPRISE (remplace l'icône générique)
        if user.get('logo'):
            try:
                import base64 as b64
                # Vérifier si le logo est déjà en base64 ou si c'est des bytes
                logo_data = user['logo']
                if isinstance(logo_data, str):
                    # C'est déjà en base64
                    st.markdown(
                        f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_data}" width="150" style="border-radius: 8px;"></div>',
                        unsafe_allow_html=True
                    )
                else:
                    # C'est des bytes, il faut encoder
                    logo_b64 = b64.b64encode(logo_data).decode('utf-8')
                    st.markdown(
                        f'<div style="text-align: center;"><img src="data:image/png;base64,{logo_b64}" width="150" style="border-radius: 8px;"></div>',
                        unsafe_allow_html=True
                    )
            except Exception as e:
                # Icône par défaut en cas d'erreur
                st.markdown('<div style="text-align: center; font-size: 48px;">🏢</div>', unsafe_allow_html=True)
        else:
            # Icône par défaut si pas de logo
            st.markdown('<div style="text-align: center; font-size: 48px;">🏢</div>', unsafe_allow_html=True)
        
        st.write(f"👤 **{user.get('contact_nom', 'Utilisateur')}**")
        st.write(f"🏢 **{user.get('nom_entreprise', 'Entreprise')}**")
        st.write(f"📍 {user.get('ville', '')}, {user.get('province', '')}")
        
        if st.button("🚪 Déconnexion", use_container_width=False):
            try:
                supabase.auth.sign_out()
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()
    
    # Charger les projets antérieurs
    try:
        apply_supabase_auth()
        projets_response = supabase.table('projets_antecedents').select("*").eq(
            'entreprise_id', user['id']
        ).execute()
        projets_antecedents = projets_response.data if projets_response.data else []
    except Exception as e:
        st.warning(f"⚠️ Erreur lors du chargement des projets : {str(e)}")
        projets_antecedents = []

    # ONGLETS PRINCIPAUX
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 Tableau de bord", 
        "🔍 Nouvelle analyse", 
        "🏗️ Projets antérieurs", 
        "👤 Mon profil"
    ])
    
    # ONGLET 1 : TABLEAU DE BORD
    with tab1:
        st.header("📊 Tableau de bord")
        
        try:
            apply_supabase_auth()
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                try:
                    projets = supabase.table('projets_antecedents').select(
                        "id", count="exact"
                    ).eq('entreprise_id', user['id']).execute()
                    st.metric("🏗️ Projets réalisés", projets.count if projets.count else 0)
                except Exception:
                    st.metric("🏗️ Projets réalisés", "0")
            
            with col2:
                try:
                    soumissions = supabase.table('soumissions').select(
                        "id", count="exact"
                    ).eq('entreprise_id', user['id']).execute()
                    st.metric("📄 Soumissions analysées", soumissions.count if soumissions.count else 0)
                except Exception:
                    st.metric("📄 Soumissions analysées", "0")
            
            with col3:
                try:
                    qualifies = supabase.table('soumissions').select(
                        "id", count="exact"
                    ).eq('entreprise_id', user['id']).eq('statut', 'qualifie').execute()
                    st.metric("✅ Qualifiées", qualifies.count if qualifies.count else 0)
                except Exception:
                    st.metric("✅ Qualifiées", "0")
            
            st.markdown("---")
            st.subheader("📈 Dernières analyses")
            
            try:
                recent = supabase.table('soumissions').select("*").eq(
                    'entreprise_id', user['id']
                ).order('created_at', desc=True).limit(5).execute()
                
                if recent.data and len(recent.data) > 0:
                    for item in recent.data:
                        with st.expander(f"📄 {item.get('nom_projet', 'Sans nom')} - {item.get('created_at', '')[:10]}"):
                            st.write(f"**Statut :** {item.get('statut', 'N/A')}")
                            st.write(f"**Recommandation :** {item.get('recommendation', 'N/A')}")
                            st.write(f"**Score :** {item.get('score', 'N/A')}")
                else:
                    st.info("📭 Aucune analyse récente")
            except Exception as e:
                st.warning(f"⚠️ Impossible de charger les analyses récentes : {str(e)}")
                
        except Exception as e:
            st.error(f"❌ Erreur lors du chargement du tableau de bord : {str(e)}")
    
    # ONGLET 2 : NOUVELLE ANALYSE
    with tab2:
        st.header("🔍 Lancer une préqualification")
        
        with st.form("analyse_form"):
            numero_projet = st.text_input("🔢 Numéro du projet")
            nom_projet = st.text_input("📋 Nom du projet")
            uploaded_file = st.file_uploader("📄 PDF Appel d'offre", type=['pdf'])
            submit = st.form_submit_button("🚀 Lancer l'analyse", use_container_width=False)
        
        if submit and uploaded_file:
            if not nom_projet:
                st.error("❌ Le nom du projet est obligatoire")
            else:
                with st.spinner("🤖 Analyse IA en cours..."):
                    try:
                        # Extraction du texte du PDF
                        reader = PdfReader(uploaded_file)
                        text = " ".join([
                            page.extract_text() or "" for page in reader.pages
                        ])[:8000]
                        
                        if not text.strip():
                            st.error("❌ Le PDF semble vide ou le texte n'a pas pu être extrait")
                            st.stop()
                        
                        today = datetime.today()
                        today_str = today.strftime("%Y-%m-%d")
                        
                        # Formater les projets antérieurs
                        projets_text = "\n".join([
                            f"- {p['nom_projet']} ({p['montant']}$, {p['duree_jours']} jours): {p['specifications']}"
                            for p in projets_antecedents
                        ]) if projets_antecedents else "Aucun projet antérieur fourni."
                        
                        # PROMPT COMPLET
                        prompt_with_context = f"""
Analysez cet appel d'offres PUBLIC (adressé à toutes les entreprises) pour déterminer si l'entreprise doit soumissionner.

Informations sur l'entreprise :
- Nom : {user.get('nom_entreprise', 'N/A')}
- Spécialités : {', '.join(user.get('specialites', [])) if user.get('specialites') else 'Non spécifiées'}
- NEQ : {user.get('numero_neq', 'N/A')}
- Licence RBQ : {user.get('licence_rbq', 'N/A')}
- Adresse : {user.get('adresse', '')}, {user.get('ville', '')}, {user.get('province', '')} {user.get('code_postal', '')}
- Contact : {user.get('contact_nom', '')}, {user.get('contact_telephone', '')}, {user.get('contact_email', '')}

Projets antérieurs pertinents :
{projets_text}

DATE DU JOUR : {today_str}

═══════════════════════════════════════════════════════════════
📋 INSTRUCTIONS CRITIQUES POUR L'ANALYSE - À RESPECTER ABSOLUMENT
═══════════════════════════════════════════════════════════════

🎯 OBJECTIF : Analyser cet appel d'offres PUBLIC (adressé à toutes les entreprises) pour déterminer si l'entreprise doit soumissionner.

⚠️ CONTEXTE IMPORTANT :
- Cet appel d'offres est PUBLIC et ouvert à toutes les entreprises qualifiées
- L'analyse doit déterminer si CETTE entreprise spécifique devrait soumissionner
- Comparer les exigences avec le profil et l'expérience de l'entreprise

📝 STYLE D'ÉCRITURE OBLIGATOIRE :
- Dans l'ANALYSE : Utiliser UNIQUEMENT la 2ème ou 3ème personne du singulier/pluriel
  ✅ "Vous possédez", "L'entreprise a", "Elle dispose", "Ils ont"
  ❌ JAMAIS "Je pense", "J'estime", "Nous pensons"
- Dans la RECOMMANDATION FINALE : Utiliser la 1ère personne
  ✅ "Je recommande GO", "Je suggère de ne pas soumissionner"
- Être concis, précis et professionnel
- Éviter les phrases trop longues
- Aller droit au but

⚠️ AVERTISSEMENT IA OBLIGATOIRE :
COMMENCER l'analyse par :
"⚠️ AVERTISSEMENT : Cette analyse est générée par un système d'intelligence artificielle. Bien que nous nous efforcions de fournir des informations précises basées sur le document fourni, des erreurs d'interprétation peuvent survenir. Il est impératif de vérifier personnellement toutes les informations critiques dans le document original avant de prendre une décision."

📅 ANALYSE DES DATES - TRÈS CRITIQUE :

1. **Date de visite des lieux** :
   - Identifier la date de visite dans le document
   - Calculer le délai entre AUJOURD'HUI ({today_str}) et la date de visite
   - Si délai < 5 jours ouvrables : 
     ⚠️ POINT FAIBLE MAJEUR : "La visite des lieux est prévue le [DATE], soit dans seulement X jours ouvrables. Ce délai très court peut compliquer l'organisation et la participation à la visite obligatoire."
   - Si délai ≥ 5 jours ouvrables :
     ✅ POINT FORT : "La visite des lieux est prévue le [DATE], soit dans X jours ouvrables, ce qui laisse un délai raisonnable pour s'organiser."

2. **Délai visite → clôture** :
   - Identifier la date de clôture/dépôt des soumissions
   - Calculer jours ouvrables entre visite et clôture
   - Si < 5 jours ouvrables :
     ⚠️ POINT FAIBLE : "Le délai entre la visite et la clôture est de seulement X jours ouvrables, ce qui est insuffisant pour préparer une soumission complète après la visite."
   - Si ≥ 5 jours ouvrables :
     ✅ POINT NEUTRE : Mentionner simplement le délai

🚫 INFORMATIONS NON DISPONIBLES - NE PAS INVENTER :
- NE PAS mentionner les assurances si non trouvées dans le document
- NE PAS mentionner le cautionnement si non trouvé dans le document  
- NE PAS inventer de montants, dates ou exigences
- SI une information n'est PAS dans le document : indiquer clairement "Information non disponible dans le document"
- Se limiter STRICTEMENT aux informations présentes dans le document fourni

🏗️ COMPARAISON AVEC PROJETS ANTÉRIEURS :
- Comparer le montant estimé avec les projets antérieurs
- Comparer la durée estimée avec les projets antérieurs
- Comparer le type de travaux avec les spécifications des projets antérieurs
- Si AUCUNE expérience similaire : 
  "L'entreprise n'a pas de projet similaire dans son historique. Elle devra démontrer sa capacité à réaliser ce type de travaux par d'autres moyens (références, sous-traitants, partenariats)."
- Si expérience similaire : 
  "L'entreprise a déjà réalisé des projets comparables, notamment [liste avec montants et durées], ce qui démontre sa capacité à réaliser ce type de travaux."

📊 STRUCTURE DE LA RÉPONSE :

1. **AVERTISSEMENT IA** (obligatoire en haut)

2. **CONTEXTE DE L'APPEL D'OFFRES**
   - "Cet appel d'offres public est ouvert à toutes les entreprises qualifiées."
   - Nature du projet en 1-2 phrases
   - Principal enjeu pour CETTE entreprise

3. **DATES CLÉS ET DÉLAIS** ⏰
   - Date du jour : {today_str}
   - Date visite : [DATE] → Délai : X jours ouvrables [✅/⚠️/❌]
   - Date clôture : [DATE]
   - Délai visite → clôture : X jours ouvrables [✅/⚠️/❌]
   - Date début travaux : [DATE si disponible]
   - Date fin travaux : [DATE si disponible]
   - Durée totale : X jours [si disponible]

4. **ADÉQUATION AVEC L'EXPÉRIENCE** 🏗️
   - Comparaison détaillée avec projets antérieurs
   - Points de correspondance ou différences majeures
   - Montants comparables ? Durées similaires ? Types de travaux ?

5. **POINTS FORTS** ✅ (maximum 5 points)
   - Chaque point avec référence précise : (Réf: Page X, Section Y)
   - Inclure les délais raisonnables si applicable

6. **POINTS FAIBLES** ⚠️ (maximum 5 points)
   - Chaque point avec référence précise ou [Information non disponible]
   - Inclure les délais courts si applicable
   - Inclure le manque d'expérience similaire si applicable

7. **CRITÈRES D'ADMISSIBILITÉ** 📋
   - UNIQUEMENT mentionner ce qui est TROUVÉ dans le document
   - Licence RBQ : [OUI/NON/NON SPÉCIFIÉ] - Référence : Page X
   - Si assurances TROUVÉES : [Montant/Type] - Référence : Page X
   - Si cautionnement TROUVÉ : [Montant/%] - Référence : Page X
   - Expérience minimale : [Description si trouvée] - Référence : Page X
   - NE PAS inventer ces informations si absentes

8. **ACTIONS PRIORITAIRES** 🎯 (maximum 5 actions concrètes)
   - 🔴 URGENT : [Action avec date limite si délai court]
   - 🟠 IMPORTANT : [Action nécessaire]
   - 🟡 À PRÉVOIR : [Action recommandée]

9. **RECOMMANDATION FINALE** 💭 (ici utiliser 1ère personne)
   - "Je recommande GO" / "Je recommande NO-GO" / "Je recommande PEUT-ÊTRE"
   - Justification en 2-3 paragraphes CONCIS
   - Mentionner les facteurs décisifs

10. **SCORE** : X/100
    - Justification du score en 1-2 phrases

═══════════════════════════════════════════════════════════════

⚠️ RAPPELS FINAUX :
- ✅ Appel d'offres PUBLIC pour toutes entreprises
- ✅ Comparer date visite avec AUJOURD'HUI ({today_str})
- ✅ Vérifier délai visite → clôture (min 5 jours ouvrables)
- ✅ 2ème/3ème personne dans l'analyse
- ✅ 1ère personne dans la recommandation
- ✅ Ne mentionner que les infos TROUVÉES dans le document
- ❌ NE PAS inventer assurances/cautionnement si absents
- ✅ Comparer avec projets antérieurs
- ✅ Être CONCIS et PRÉCIS

### Appel d'offre à analyser :
{text}
"""
                        
                        # Analyse avec LLM
                        analysis_result = llm_manager.analyze(prompt_with_context, max_tokens=2500)
                        
                        if not analysis_result["success"]:
                            st.error(f"❌ {analysis_result['error']}")
                            st.stop()
                        
                        result = analysis_result["result"]
                        
                        # Affichage du résultat
                        st.markdown("### 📋 Résultat de l'analyse IA")
                        st.markdown("---")
                        st.markdown(result)
                        
                        # Extraction de la recommandation
                        rec = "INCONNU"
                        result_upper = result.upper()
                        if "JE RECOMMANDE GO" in result_upper and "NO-GO" not in result_upper and "NO GO" not in result_upper:
                            rec = "GO"
                        elif "NO-GO" in result_upper or "NO GO" in result_upper or "JE RECOMMANDE NO" in result_upper:
                            rec = "NO-GO"
                        elif "PEUT-ÊTRE" in result_upper or "MAYBE" in result_upper or "PEUT ÊTRE" in result_upper:
                            rec = "PEUT-ÊTRE"
                        
                        # Extraction du score
                        score = 0
                        score_match = re.search(r"(?:Score|SCORE)\s*[:\-]?\s*(\d+)", result, re.IGNORECASE)
                        if score_match:
                            score = int(score_match.group(1))
                        
                        # Sauvegarde
                        soumission_data = {
                            "numero_projet": numero_projet,
                            "nom_projet": nom_projet,
                            "document": uploaded_file,
                            "analyse_json": {
                                "raw_response": result
                            },
                            "recommendation": rec,
                            "score": score,
                            "statut": "qualifie" if rec == "GO" else "non_qualifie"
                        }
                        
                        soumission = save_soumission(user['id'], soumission_data)
                        
                        if soumission:
                            st.success("✅ Analyse sauvegardée dans la base de données !")
                        else:
                            st.warning("⚠️ L'analyse a été effectuée mais n'a pas pu être sauvegardée")
                    
                    except Exception as e:
                        st.error(f"❌ Erreur lors de l'analyse : {str(e)}")
        elif submit:
            st.error("❌ Veuillez uploader un fichier PDF")
    
    # ONGLET 3 : PROJETS ANTÉRIEURS
    with tab3:
        st.header("🏗️ Vos projets antérieurs")
        
        with st.expander("➕ Ajouter un projet"):
            with st.form("add_projet"):
                col1, col2 = st.columns(2)
                with col1:
                    nom_p = st.text_input("Nom du projet *")
                    montant_p = st.number_input("Montant ($)", min_value=0, value=0)
                    duree_p = st.number_input("Durée (jours)", min_value=1, value=1)
                with col2:
                    specs_p = st.text_area("Spécifications")
                    doc_p = st.file_uploader("Document PDF (optionnel)", type=["pdf"])
                
                if st.form_submit_button("💾 Ajouter", use_container_width=False):
                    if not nom_p:
                        st.error("❌ Le nom du projet est obligatoire")
                    else:
                        if add_projet_antecedent({
                            "nom_projet": nom_p,
                            "montant": montant_p,
                            "duree_jours": duree_p,
                            "specifications": specs_p,
                            "document": doc_p
                        }):
                            st.rerun()
        
        # Liste des projets
        try:
            apply_supabase_auth()
            projets = supabase.table('projets_antecedents').select("*").eq(
                'entreprise_id', user['id']
            ).order('created_at', desc=True).execute()
            
            if not projets.data or len(projets.data) == 0:
                st.info("📭 Aucun projet pour le moment")
            else:
                for projet in projets.data:
                    with st.expander(f"🏗️ {projet.get('nom_projet', 'Sans nom')}"):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.write(f"**Montant :** {projet.get('montant', 0):,.2f} $")
                            st.write(f"**Durée :** {projet.get('duree_jours', 0)} jours")
                        with col_b:
                            st.write(f"**Date :** {projet.get('created_at', '')[:10]}")
                            if projet.get('document_url'):
                                st.markdown(f"[📄 Voir document]({projet['document_url']})")
                        st.write(f"**Spécifications :** {projet.get('specifications', 'Aucune')}")
        except Exception as e:
            st.error(f"❌ Erreur lors du chargement des projets : {str(e)}")
    
    # ONGLET 4 : PROFIL
    with tab4:
        st.header("👤 Vos informations")
        
        st.subheader("Entreprise")
        st.write(f"**Nom :** {user.get('nom_entreprise', 'N/A')}")
        st.write(f"**NEQ :** {user.get('numero_neq', 'N/A')}")
        st.write(f"**Licence RBQ :** {user.get('licence_rbq', 'N/A')}")
        st.write(f"**Spécialités :** {', '.join(user.get('specialites', [])) if user.get('specialites') else 'Aucune'}")
        st.write(f"**Adresse :** {user.get('adresse', '')}, {user.get('ville', '')}, {user.get('province', '')} {user.get('code_postal', '')}")
        
        st.subheader("Contact")
        st.write(f"**Nom :** {user.get('contact_nom', 'N/A')}")
        st.write(f"**Téléphone :** {user.get('contact_telephone', 'N/A')}")
        st.write(f"**Courriel :** {user.get('contact_email', 'N/A')}")
        
        st.subheader("Logo de l'entreprise")
        
        col_logo, col_upload = st.columns([1, 1])
        
        with col_logo:
            # AFFICHAGE DU LOGO ACTUEL
            if user.get('logo'):
                try:
                    import base64 as b64
                    logo_data = user['logo']
                    if isinstance(logo_data, str):
                        st.markdown(
                            f'<img src="data:image/png;base64,{logo_data}" width="200" style="border-radius: 8px; border: 2px solid #1E90FF;">',
                            unsafe_allow_html=True
                        )
                        st.caption("✅ Logo actuel")
                    else:
                        logo_b64 = b64.b64encode(logo_data).decode('utf-8')
                        st.markdown(
                            f'<img src="data:image/png;base64,{logo_b64}" width="200" style="border-radius: 8px; border: 2px solid #1E90FF;">',
                            unsafe_allow_html=True
                        )
                        st.caption("✅ Logo actuel")
                except Exception:
                    st.caption("⚠️ Logo actuel indisponible")
            else:
                st.info("📷 Aucun logo enregistré")
        
        with col_upload:
            # FORMULAIRE DE REMPLACEMENT DU LOGO
            with st.form("update_logo_form"):
                st.write("**Remplacer le logo**")
                new_logo = st.file_uploader(
                    "Choisir un nouveau logo",
                    type=['png', 'jpg', 'jpeg'],
                    help="Formats acceptés: PNG, JPG, JPEG (max 2MB)"
                )
                submit_logo = st.form_submit_button("📤 Uploader le nouveau logo")
                
                if submit_logo and new_logo:
                    try:
                        # Validation taille
                        if new_logo.size > 2 * 1024 * 1024:
                            st.error("❌ Le logo doit faire moins de 2 MB")
                        else:
                            apply_supabase_auth()
                            
                            # Encoder en base64
                            logo_bytes = new_logo.read()
                            logo_base64 = base64.b64encode(logo_bytes).decode('utf-8')
                            
                            # Mettre à jour dans la DB
                            result = supabase.table('entreprises').update({
                                "logo": logo_base64
                            }).eq('id', user['id']).execute()
                            
                            if result.data and len(result.data) > 0:
                                # Recharger l'utilisateur
                                user_updated = supabase.table('entreprises').select("*").eq(
                                    'id', user['id']
                                ).execute()
                                
                                if user_updated.data and len(user_updated.data) > 0:
                                    st.session_state.user = user_updated.data[0]
                                    st.success("✅ Logo remplacé avec succès !")
                                    st.info("🔄 Rechargement de la page pour afficher le nouveau logo...")
                                    import time
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                st.error("❌ Erreur lors du remplacement du logo")
                                
                    except Exception as e:
                        st.error(f"❌ Erreur lors de l'upload : {str(e)}")
                elif submit_logo and not new_logo:
                    st.warning("⚠️ Veuillez sélectionner un fichier")
        
        st.markdown("---")
        
        if st.button("✏️ Modifier le profil complet"):
            st.session_state.profile_completed = False
            st.rerun()
