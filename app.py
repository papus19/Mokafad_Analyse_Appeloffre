import streamlit as st
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from pypdf import PdfReader
import forms
import storage
from groq import Groq
import google.generativeai as genai
from openai import OpenAI

# --- CONFIGURATION ---
load_dotenv()
st.set_page_config(page_title="⚡ MOKAFAD - Solution Soumission IA", page_icon="⚡", layout="wide")

# --- STYLE BLEU CIEL + SUPPRESSION FOOTER ---
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
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #104E8B !important;
        font-weight: 600 !important;
        padding: 0.75rem 1.5rem !important;
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
    .profile-section {
        background-color: white;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 6px rgba(176, 224, 230, 0.5);
    }
    .profile-logo {
        width: 120px;
        height: 120px;
        border-radius: 50%;
        background-color: #E6F7FF;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 2.5rem;
        color: #1E90FF;
        font-weight: bold;
    }
    /* SUPPRESSION FOOTER STREAMLIT */
    [data-testid="stAppViewFooter"] {
        display: none !important;
    }
    footer {
        visibility: hidden !important;
    }
    /* Suppression bouton deploy */
    #MainMenu {
        visibility: hidden !important;
    }
</style>
""", unsafe_allow_html=True)

# --- VÉRIFICATION DES CLÉS ---
required_vars = ["SUPABASE_URL", "SUPABASE_ANON_KEY"]
missing = [var for var in required_vars if not os.getenv(var)]
if missing:
    st.error(f"❌ Variables manquantes dans .env : {', '.join(missing)}")
    st.code("""
📁 Fichier .env requis :
SUPABASE_URL=https://votre-projet.supabase.co      
SUPABASE_ANON_KEY=eyJxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Au moins une clé API IA (Gemini en priorité):
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    """)
    st.stop()

# --- CLIENTS ---
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_ANON_KEY")
)

# --- VÉRIFICATION DE LA SESSION AU DÉMARRAGE (APRÈS INITIALISATION SUPABASE) ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    
if 'user' not in st.session_state:
    st.session_state.user = None
    
if 'profile_completed' not in st.session_state:
    st.session_state.profile_completed = False

# ✅ Vérification de l'authentification existante
try:
    current_session = supabase.auth.get_session()
    if current_session and not st.session_state.logged_in:
        st.info("🔄 Session existante détectée, récupération des données...")
        result = supabase.table('entreprises').select("*").eq('contact_email', current_session.user.email).execute()
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            st.success("✅ Session restaurée automatiquement")
except:
    pass  # Pas de session existante

# --- CONFIGURATION MULTI-LLM AVEC GEMINI EN PRIORITÉ ABSOLUE ---
class MultiLLMClient:
    """Client qui gère plusieurs LLMs avec fallback automatique - Gemini en priorité absolue"""
    
    def __init__(self):
        self.providers = []
        
        # ✅ PRIORITÉ 1 : Gemini 1.5 Flash (modèle OFFICIEL - CORRECTION)
        if os.getenv("GEMINI_API_KEY"):
            try:
                genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
                # CORRECTION : 'gemini-2.5-flash' n'existe pas → utiliser 'gemini-1.5-flash'
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
                self.providers.append("gemini")
            except Exception as e:
                st.warning(f"⚠️ Gemini non configuré: {str(e)}")
        
        # ✅ PRIORITÉ 2 : Groq (LLaMA 3.3)
        if os.getenv("GROQ_API_KEY"):
            try:
                self.groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
                self.providers.append("groq")
            except:
                pass
        
        # ✅ PRIORITÉ 3 : OpenAI (fallback)
        if os.getenv("OPENAI_API_KEY"):
            try:
                self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                self.providers.append("openai")
            except:
                pass
        
        if not self.providers:
            st.error("❌ Aucune clé API IA configurée. Ajoutez GEMINI_API_KEY dans .env")
            st.stop()
    
    def analyze(self, prompt: str, max_tokens: int = 4500) -> tuple:
        """Essaie chaque provider dans l'ordre de priorité"""
        for provider in self.providers:
            try:
                if provider == "gemini":
                    response = self.gemini_model.generate_content(
                        prompt,
                        generation_config=genai.types.GenerationConfig(
                            max_output_tokens=max_tokens,
                            temperature=0.2,
                        )
                    )
                    return response.text, "Gemini 1.5 Flash"
                
                elif provider == "groq":
                    response = self.groq_client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                        max_tokens=max_tokens,
                        temperature=0.2,
                        top_p=0.9
                    )
                    return response.choices[0].message.content, "Groq (LLaMA 3.3)"
                
                elif provider == "openai":
                    response = self.openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=max_tokens,
                        temperature=0.2
                    )
                    return response.choices[0].message.content, "OpenAI GPT-3.5"
                
            except Exception as e:
                continue
        
        raise Exception("Tous les services IA sont temporairement indisponibles. Réessayez plus tard.")

# Initialiser le client multi-LLM
llm_client = MultiLLMClient()

# --- FONCTION D'ANALYSE AVEC COMPARAISON DES PROJETS ANTÉRIEURS ---
def analyze_document(prompt: str, user: dict, entreprise_id: str) -> tuple:
    """Analyse un document avec le meilleur LLM disponible + comparaison avec projets antérieurs"""
    try:
        # Récupérer les projets antérieurs de l'entreprise
        projets_anterieurs = supabase.table('projets_antecedents').select("*").eq('entreprise_id', entreprise_id).order('created_at', desc=True).limit(5).execute()
        
        # Formatage des projets antérieurs
        projets_text = "\n\n### PROJETS ANTÉRIEURS :\n"
        if projets_anterieurs.data:
            for i, projet in enumerate(projets_anterieurs.data):
                projets_text += f"Projet #{i+1}: {projet['nom_projet']} (Montant: ${projet['montant']:.2f}, Durée: {projet['duree_jours']} jours)\n"
                projets_text += f"  Spécifications: {projet['specifications'][:150]}...\n"
                if projet.get('document_url'):
                    projets_text += f"  Document: {projet['document_url']}\n"
        else:
            projets_text += "Aucun projet antérieur trouvé\n"
        
        # Ajouter les projets antérieurs au prompt
        prompt_with_history = f"""
        {prompt}
        
        {projets_text}
        
        INSTRUCTIONS SUPPLÉMENTAIRES:
        - Comparez cet appel d'offre avec les projets antérieurs
        - Identifiez les similitudes et différences clés
        - Évaluez l'adéquation avec l'expérience de l'entreprise
        - Suggérez des adaptations nécessaires par rapport aux projets antérieurs
        - ✅ **Veuillez terminer votre réponse COMPLÈTEMENT sans couper les phrases**
        """
        
        result, model_used = llm_client.analyze(prompt_with_history, max_tokens=4500)
        return result, model_used
    except Exception as e:
        raise Exception(f"Erreur analyse IA : {str(e)}")

# --- FONCTIONS BASE DE DONNÉES ---
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
        if not result.data:
            raise Exception("❌ Échec de création de l'entreprise")
        
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
        st.success(f"✅ Authentification réussie - User ID: {session.user.id}")
        
        # 🔍 Chercher l'entreprise
        result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
        
        if result.data:
            st.session_state.user = result.data[0]
            st.session_state.logged_in = True
            st.session_state.profile_completed = bool(st.session_state.user.get('logo_url'))
            st.success("✅ Connexion réussie !")
            return True
            
        else:
            # ✅ CAS CRITIQUE : Aucune entreprise trouvée (mais utilisateur authentifié)
            st.warning("⚠️ Votre profil n'est pas complété. Veuillez compléter votre profil.")
            
            # Créer un état temporaire pour rediriger vers la complétion
            st.session_state.user = {
                "contact_email": email,
                "user_id": session.user.id
            }
            st.session_state.logged_in = True
            st.session_state.profile_completed = False
            
            st.success("✅ Redirection vers la complétion du profil...")
            return True  # ✅ Retourne True pour autoriser la redirection
            
    except Exception as e:
        st.error(f"❌ Erreur: {str(e)}")
        return False

def get_user_by_email(email):
    result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
    return result.data[0] if result.data else None

def update_entreprise_profile(entreprise_id, data):
    try:
        logo_file = data.pop("logo_file", None)
        if logo_file:
            logo_url = storage.upload_logo(supabase, logo_file)
            if logo_url:
                data["logo_url"] = logo_url
        if data:
            supabase.table('entreprises').update(data).eq('id', entreprise_id).execute()
        return True
    except Exception as e:
        st.error(f"Erreur mise à jour profil: {str(e)}")
        return False

def add_projet_antecedent(projet_data):
    try:
        # ✅ Vérifiez que l'utilisateur est bien connecté
        if not st.session_state.user:
            raise Exception("❌ Utilisateur non authentifié")
        
        # ✅ Vérifiez que l'ID de l'entreprise existe
        entreprise_id = st.session_state.user.get('id')
        if not entreprise_id:
            raise Exception("❌ ID de l'entreprise manquant")
        
        data = {
            "entreprise_id": entreprise_id,
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

def save_soumission(entreprise_id, data):
    try:
        document_file = data.pop("document", None)
        if document_file:
            doc_url = storage.upload_soumission(supabase, document_file)
            if doc_url:
                data["document_url"] = doc_url
        data["entreprise_id"] = entreprise_id
        result = supabase.table('soumissions').insert(data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Erreur sauvegarde soumission: {str(e)}")
        return None

# --- APPLICATION ---
st.title("⚡ MOKAFAD - Solution Soumission IA")

# --- AUTHENTIFICATION ---
if not st.session_state.logged_in:
    tab1, tab2 = st.tabs(["🔐 Connexion", "📝 Inscription"])
    with tab1:
        with st.form("login_form"):
            email = st.text_input("📧 Email")
            password = st.text_input("🔒 Mot de passe", type="password")
            if st.form_submit_button("➡️ Se connecter", use_container_width=False):
                st.info("🔄 Tentative de connexion en cours...")
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
        if profile_data["logo_file"]:
            logo_url = storage.upload_logo(supabase, profile_data["logo_file"])
            if logo_url:
                update_entreprise_profile(st.session_state.user['id'], {"logo_url": logo_url})
                user_updated = supabase.table('entreprises').select("*").eq('id', st.session_state.user['id']).execute()
                st.session_state.user = user_updated.data[0]
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
            st.image(user['logo_url'], width=120)
        else:
            # ✅ CORRECTION : Utilisez .get() avec valeur par défaut
            nom_entreprise = user.get('nom_entreprise', 'Entreprise')
            initiales = "".join([part[0].upper() for part in nom_entreprise.split()[:2]])
            st.markdown(f'<div class="profile-logo">{initiales}</div>', unsafe_allow_html=True)
        
        st.write(f"👤 **{user.get('contact_nom', 'N/A')}**")
        st.write(f"🏢 **{user.get('nom_entreprise', 'N/A')}**")
        st.write(f"📍 {user.get('ville', 'N/A')}, {user.get('province', 'N/A')}")
        
        st.markdown("---")
        projets = supabase.table('projets_antecedents').select("id", count="exact").eq('entreprise_id', user['id']).execute()
        soumissions = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).execute()
        qualifies = supabase.table('soumissions').select("id", count="exact").eq('entreprise_id', user['id']).eq('statut', 'qualifie').execute()
        
        st.metric("🏗️ Projets", projets.count)
        st.metric("📄 Soumissions", soumissions.count)
        st.metric("✅ Qualifiées", qualifies.count)
        
        if st.button("🚪 Déconnexion", use_container_width=False):
            supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()
    
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Tableau de bord", "👤 Mon Profil", "🔍 Nouvelle analyse", "🏗️ Projets antérieurs"])
    
    # --- TAB 1 : TABLEAU DE BORD ---
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
                    col_status, col_rec = st.columns(2)
                    with col_status:
                        st.write(f"**Statut:** {item['statut']}")
                        st.write(f"**Score:** {item.get('score', 'N/A')}")
                    with col_rec:
                        st.write(f"**Recommandation:** {item.get('recommendation', 'N/A')}")
                        st.write(f"**Numéro projet:** {item.get('numero_projet', 'N/A')}")
                    
                    if item.get('document_url'):
                        st.markdown(f"[📄 Voir le document PDF]({item['document_url']})")
                    
                    if item.get('analyse_json') and item['analyse_json'].get('raw_response'):
                        st.markdown("---")
                        st.markdown("### 🤖 Résultat de l'analyse IA")
                        st.markdown(item['analyse_json']['raw_response'])
        else:
            st.info("📭 Aucune analyse récente")
    
    # --- TAB 2 : MON PROFIL ---
    with tab2:
        st.header("👤 Mon Profil Entreprise")
        
        st.markdown('<div class="profile-section">', unsafe_allow_html=True)
        st.subheader("🖼️ Logo de l'entreprise")
        
        col_logo1, col_logo2 = st.columns([1, 3])
        with col_logo1:
            if user.get('logo_url'):
                st.image(user['logo_url'], width=150)
            else:
                # ✅ CORRECTION : Utilisez .get() avec valeur par défaut
                nom_entreprise = user.get('nom_entreprise', 'Entreprise')
                initiales = "".join([part[0].upper() for part in nom_entreprise.split()[:2]])
                st.markdown(f'<div class="profile-logo" style="width:150px;height:150px;font-size:3rem;">{initiales}</div>', unsafe_allow_html=True)
        
        with col_logo2:
            st.write("**Modifier le logo**")
            new_logo = st.file_uploader("Téléverser un nouveau logo (PNG, JPG)", type=["png", "jpg", "jpeg"], key="logo_uploader")
            if new_logo and st.button("💾 Changer le logo", key="save_logo"):
                try:
                    logo_url = storage.upload_logo(supabase, new_logo)
                    if logo_url:
                        supabase.table('entreprises').update({"logo_url": logo_url}).eq('id', user['id']).execute()
                        user_updated = supabase.table('entreprises').select("*").eq('id', user['id']).execute()
                        st.session_state.user = user_updated.data[0]
                        st.success("✅ Logo mis à jour !")
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ Erreur: {str(e)}")
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="profile-section">', unsafe_allow_html=True)
        st.subheader("✏️ Informations de l'entreprise")
        
        with st.form("update_profile_form"):
            col1, col2 = st.columns(2)
            
            with col1:
                nom_entreprise = st.text_input("🏢 Nom de l'entreprise *", value=user.get('nom_entreprise', ''))
                neq = st.text_input("🔢 Numéro NEQ", value=user.get('numero_neq', ''))
                rbq = st.text_input("📋 Licence RBQ", value=user.get('licence_rbq', ''))
                
                options_specialites = ["Électricité Résidentiel", "Électricité Commerciale"]
                current_specialites = user.get('specialites', [])
                if current_specialites is None:
                    current_specialites = []
                default_specialites = [s for s in current_specialites if s in options_specialites]
                
                specialites = st.multiselect(
                    "⚡ Spécialités *",
                    options_specialites,
                    default=default_specialites,
                    help="Sélectionnez vos spécialités"
                )
            
            with col2:
                st.subheader("📍 Adresse")
                rue = st.text_input("Rue *", value=user.get('adresse', ''))
                ville = st.text_input("Ville *", value=user.get('ville', ''))
                province = st.selectbox("Province *", ["Québec"], index=0)
                code_postal = st.text_input("Code postal *", value=user.get('code_postal', ''))
                pays = st.selectbox("Pays *", ["Canada"], index=0)
            
            st.markdown("---")
            st.subheader("👤 Contact principal")
            
            col3, col4 = st.columns(2)
            with col3:
                contact_nom = st.text_input("Nom complet *", value=user.get('contact_nom', ''))
                st.text_input("📧 Email *", value=user.get('contact_email', ''), disabled=True)
                st.caption("💡 Pour modifier l'email, contactez le support")
            
            with col4:
                contact_telephone = st.text_input("📱 Téléphone *", value=user.get('contact_telephone', ''))
                pwd_confirm = st.text_input("🔒 Confirmer avec mot de passe *", type="password", help="Entrez votre mot de passe pour confirmer les modifications")
            
            if st.form_submit_button("💾 Sauvegarder les modifications", use_container_width=False):
                if not pwd_confirm:
                    st.error("❌ Veuillez entrer votre mot de passe pour confirmer")
                elif not nom_entreprise or not specialites or not rue or not ville or not code_postal or not contact_nom or not contact_telephone:
                    st.error("❌ Tous les champs marqués * sont requis")
                else:
                    try:
                        session = supabase.auth.sign_in_with_password({
                            "email": user['contact_email'], 
                            "password": pwd_confirm
                        })
                        update_data = {
                            "nom_entreprise": nom_entreprise,
                            "numero_neq": neq,
                            "licence_rbq": rbq,
                            "specialites": specialites,
                            "adresse": rue,
                            "ville": ville,
                            "province": province,
                            "code_postal": code_postal,
                            "pays": pays,
                            "contact_nom": contact_nom,
                            "contact_telephone": contact_telephone
                        }
                        
                        if update_entreprise_profile(user['id'], update_data):
                            user_updated = supabase.table('entreprises').select("*").eq('id', user['id']).execute()
                            st.session_state.user = user_updated.data[0]
                            st.success("✅ Profil mis à jour avec succès !")
                            st.rerun()
                    except Exception as e:
                        st.error("❌ Mot de passe incorrect. Veuillez réessayer.")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # --- TAB 3 : NOUVELLE ANALYSE (CORRIGÉ) ---
    with tab3:
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
                    Entreprise: {user.get('nom_entreprise', 'N/A')}
                    Spécialités: {', '.join(user.get('specialites', []))}
                    NEQ: {user.get('numero_neq', 'N/A')}
                    Licence RBQ: {user.get('licence_rbq', 'N/A')}
                    Adresse: {user.get('adresse', 'N/A')}, {user.get('ville', 'N/A')}, {user.get('province', 'N/A')}
                    """
                    prompt = f"""
                    {context}
                    
                    INSTRUCTIONS IMPORTANTES:
                    - Ne JAMAIS inventer ou halluciner des informations
                    - Basez-vous UNIQUEMENT sur les informations présentes dans le document
                    - Citez TOUJOURS les pages ou sections spécifiques du document
                    - Si une information n'est pas dans le document, indiquez clairement "Information non trouvée dans le document"
                    - ✅ **Veuillez terminer votre réponse COMPLÈTEMENT sans couper les phrases**
                    - ✅ **N'arrêtez pas avant d'avoir fini la justification détaillée**

                    Analysez cet appel d'offre et donnez:
                    
                    1. RECOMMANDATION: GO / NO-GO / PEUT-ÊTRE
                    
                    2. SCORE: X/100 avec justification
                    
                    3. POINTS FORTS (avec références):
                    - [Point fort 1] (Référence: Page X, Section Y)
                    - [Point fort 2] (Référence: Page X, Section Y)
                    
                    4. POINTS FAIBLES (avec références):
                    - [Point faible 1] (Référence: Page X, Section Y ou "Information manquante")
                    - [Point faible 2] (Référence: Page X, Section Y ou "Information manquante")
                    
                    5. CRITÈRES D'ADMISSIBILITÉ:
                    - Licence RBQ requise: [OUI/NON/NON SPÉCIFIÉ] (Référence: Page X)
                    - Assurances requises: [Montant/Type] (Référence: Page X)
                    - Cautionnement requis: [Montant/%] (Référence: Page X)
                    - Expérience minimale: [Description] (Référence: Page X)
                    - Délai de réalisation: [X jours] (Référence: Page X)
                    - Budget estimé: [Montant] (Référence: Page X)
                    
                    6. ACTIONS RECOMMANDÉES (avec priorités):
                    - [Action 1 - URGENT/IMPORTANT/OPTIONNEL]
                    - [Action 2 - URGENT/IMPORTANT/OPTIONNEL]
                    
                    7. JUSTIFICATION DÉTAILLÉE:
                    Expliquez votre recommandation en citant des extraits précis du document avec les numéros de page.
                    
                    Document:
                    {text}
                    """
                    
                    # ✅ CORRECTION : Ajout de la comparaison avec projets antérieurs
                    result, model_used = analyze_document(prompt, user, user['id'])
                    
                    # Extraire recommandation
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
                            "model_used": model_used
                        },
                        "recommendation": rec,
                        "score": 0,
                        "statut": "qualifie" if rec == "GO" else "non_qualifie"
                    }
                    soumission = save_soumission(user['id'], soumission_data)
                    if soumission:
                        st.success(f"✅ Analyse sauvegardée ! (via {model_used})")
                        st.markdown("### 📋 Résultat IA")
                        st.markdown(result)
                    else:
                        st.error("❌ Erreur sauvegarde")
                except Exception as e:
                    st.error(f"❌ Erreur: {str(e)}")
    
    # --- TAB 4 : PROJETS ANTÉRIEURS ---
    with tab4:
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
