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
# 🆕 SYSTÈME DE FALLBACK: GEMINI EN PREMIER (SANS AFFICHAGE)
# ============================================

class LLMManager:
    def __init__(self):
        self.providers = []
        self._init_providers()
    
    def _init_providers(self):
        # GEMINI EN PREMIER COMME EXIGÉ
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
if 'show_login_tab' not in st.session_state:
    st.session_state.show_login_tab = True

def apply_supabase_auth():
    token = st.session_state.get('access_token')
    if token and isinstance(token, str) and token.strip():
        supabase.postgrest.auth(token)

# --- FONCTIONS BASE DE DONNÉES ---
def signup_user(data):
    try:
        # Validation obligatoire NEQ et RBQ
        if not data.get("numero_neq") or not data.get("licence_rbq"):
            st.error("❌ Le NEQ et la licence RBQ sont obligatoires")
            return False
            
        # Inscription sans tentative de connexion immédiate
        response = supabase.auth.sign_up({
            "email": data["contact_email"], 
            "password": data["password"]
        })
        
        # Récupérer l'ID utilisateur depuis la réponse
        user_id = response.user.id
        
        # Enregistrer les données de l'entreprise
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
            "user_id": user_id
        }

        result = supabase.table('entreprises').insert(entreprise_data).execute()
        
        if result.data:
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
            st.session_state.profile_completed = bool(st.session_state.user.get('logo'))
            return True
        return False
    except Exception as e:
        error_msg = str(e).lower()
        if "email not confirmed" in error_msg or "email_not_confirmed" in error_msg:
            st.error("📧 Votre courriel n'a pas encore été validé. Veuillez cliquer sur le lien dans le courriel de confirmation que nous vous avons envoyé. Pensez à vérifier dans vos courriels indésirables (spam).")
        else:
            st.error(f"❌ Erreur connexion: {str(e)}")
        return False

def get_user_by_email(email):
    result = supabase.table('entreprises').select("*").eq('contact_email', email).execute()
    return result.data[0] if result.data else None

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
            # Upload document projet via storage existant
            import storage
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
                import storage
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
    # Déterminer l'onglet actif après une inscription réussie
    default_tab = 0 if st.session_state.show_login_tab else 1
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
            # Validation obligatoire NEQ et RBQ AVANT soumission
            if not signup_data.get("numero_neq") or not signup_data.get("licence_rbq"):
                st.error("❌ Le NEQ et la licence RBQ sont obligatoires pour créer un compte")
            elif get_user_by_email(signup_data["contact_email"]):
                st.error("❌ Cet email est déjà utilisé")
            elif signup_user(signup_data):
                st.success("✅ Compte créé ! Un courriel de validation a été envoyé. **Pensez à vérifier dans vos courriels indésirables (spam).**")
                # Basculer vers l'onglet de connexion et réinitialiser le formulaire
                st.session_state.show_login_tab = True
                st.rerun()

# --- PROFIL À COMPLÉTER (LOGO DIRECT DANS COLONNE) ---
elif not st.session_state.profile_completed:
    st.warning("⚠️ Veuillez compléter votre profil pour continuer")
    profile_data = forms.profile_completion_form(st.session_state.user)
    if profile_data:
        apply_supabase_auth()
        # STOCKAGE DIRECT DU LOGO DANS LA COLONNE 'logo' (base64)
        if profile_data["logo_file"]:
            try:
                logo_bytes = profile_data["logo_file"].read()
                logo_base64 = base64.b64encode(logo_bytes).decode('utf-8')
                supabase.table('entreprises').update({"logo": logo_base64}).eq('id', st.session_state.user['id']).execute()
                # Recharger l'utilisateur
                user_updated = supabase.table('entreprises').select("*").eq('id', st.session_state.user['id']).execute()
                if user_updated.data:
                    st.session_state.user = user_updated.data[0]
            except Exception as e:
                st.warning(f"⚠️ Erreur lors de l'enregistrement du logo: {str(e)}")
        
        # Ajout des projets antérieurs
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
        # AFFICHAGE DU LOGO STOCKÉ EN BASE64
        if user.get('logo'):
            try:
                st.image(f"data:image/png;base64,{user['logo']}", width=150)
            except:
                st.caption("Logo indisponible")
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
                    today_str = today.strftime("%Y-%m-%d")
                    
                    # Formater les projets antérieurs pour le prompt
                    projets_text = "\n".join([
                        f"- {p['nom_projet']} ({p['montant']}$, {p['duree_jours']} jours): {p['specifications']}"
                        for p in projets_antecedents
                    ]) or "Aucun projet antérieur fourni."
                    
                    # PROMPT EXACTEMENT COMME EXIGÉ DANS LA DEMANDE
                    prompt_with_context = f"""
Analysez cet appel d'offres PUBLIC (adressé à toutes les entreprises) pour déterminer si l'entreprise doit soumissionner.

Informations sur l'entreprise :
- Nom : {user['nom_entreprise']}
- Spécialités : {', '.join(user.get('specialites', [])) or 'Non spécifiées'}
- NEQ : {user.get('numero_neq', 'N/A')}
- Licence RBQ : {user.get('licence_rbq', 'N/A')}
- Adresse : {user.get('adresse')}, {user.get('ville')}, {user.get('province')} {user.get('code_postal')}
- Contact : {user.get('contact_nom')}, {user.get('contact_telephone')}, {user.get('contact_email')}

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
                    
                    analysis_result = llm_manager.analyze(prompt_with_context, max_tokens=2500)
                    
                    if not analysis_result["success"]:
                        st.error(f"❌ {analysis_result['error']}")
                        st.stop()
                    
                    result = analysis_result["result"]
                    
                    st.markdown("### 📋 Résultat de l'analyse IA")
                    st.markdown("---")
                    st.markdown(result)  # PAS D'AFFICHAGE DU MODÈLE UTILISÉ
                    
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
                            "raw_response": result
                            # PAS DE STOCKAGE DU MODÈLE UTILISÉ
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
        
        # AFFICHAGE DU LOGO STOCKÉ EN BASE64
        if user.get('logo'):
            try:
                st.image(f"data:image/png;base64,{user['logo']}", width=200)
            except:
                st.caption("Logo indisponible")
        
        if st.button("✏️ Modifier le profil"):
            st.session_state.profile_completed = False
            st.rerun()
