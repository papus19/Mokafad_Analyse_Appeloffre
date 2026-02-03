import streamlit as st
import re

def validate_email(email):
    """Valider format email"""
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email)

def validate_password(password):
    """Valider mot de passe"""
    if len(password) < 8:
        return False, "Minimum 8 caractères"
    if not re.search(r'[A-Z]', password):
        return False, "Au moins une majuscule"
    if not re.search(r'[0-9]', password):
        return False, "Au moins un chiffre"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Au moins un caractère spécial"
    return True, ""

def signup_form():
    """Formulaire d'inscription initial - toutes les informations de base"""
    st.subheader("📝 Informations de l'entreprise")
    
    col1, col2 = st.columns(2)
    
    with col1:
        nom_entreprise = st.text_input("🏢 Nom de l'entreprise *", placeholder="Ex: Électro Québec Inc.")
        neq = st.text_input("🔢 Numéro NEQ (Québec)", placeholder="123456789")
        rbq = st.text_input("📋 Licence RBQ", placeholder="1234-5678")
        specialites = st.multiselect(
            "⚡ Spécialité(s) *",
            ["Électricité Résidentiel", "Électricité Commerciale"],
            help="Sélectionnez au moins une spécialité"
        )
    
    with col2:
        st.subheader("📍 Adresse")
        rue = st.text_input("Rue *", placeholder="123 Rue Principale")
        ville = st.text_input("Ville *", placeholder="Montréal")
        province = st.selectbox("Province *", ["Québec"], index=0)
        code_postal = st.text_input("Code postal *", placeholder="H1A 1A1")
        pays = st.selectbox("Pays *", ["Canada"], index=0)
    
    st.markdown("---")
    st.subheader("👤 Contact principal")
    
    col3, col4 = st.columns(2)
    
    with col3:
        contact_nom = st.text_input("Nom complet *", placeholder="Jean Dupont")
        contact_email = st.text_input("📧 Email *", placeholder="contact@entreprise.com")
        valid_email = validate_email(contact_email) if contact_email else None
    
    with col4:
        contact_telephone = st.text_input("📱 Téléphone *", placeholder="(514) 123-4567")
        password = st.text_input("🔒 Mot de passe *", type="password", 
                                help="8+ caractères, 1 majuscule, 1 chiffre, 1 caractère spécial")
        password_confirm = st.text_input("🔒 Confirmer mot de passe *", type="password")
    
    # Validation
    errors = []
    
    if st.button("✅ Créer mon compte", type="primary", use_container_width=True):
        if not nom_entreprise:
            errors.append("❌ Nom de l'entreprise requis")
        if not specialites:
            errors.append("❌ Sélectionnez au moins une spécialité")
        if not rue or not ville or not code_postal:
            errors.append("❌ Adresse complète requise")
        if not contact_nom or not contact_email or not contact_telephone:
            errors.append("❌ Informations de contact requises")
        
        if contact_email and not valid_email:
            errors.append("❌ Format email invalide")
        
        if password:
            valid_pwd, msg = validate_password(password)
            if not valid_pwd:
                errors.append(f"❌ Mot de passe: {msg}")
            elif password != password_confirm:
                errors.append("❌ Les mots de passe ne correspondent pas")
        
        if errors:
            for error in errors:
                st.error(error)
            return None
        
        # Retourner les données validées
        return {
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
            "contact_telephone": contact_telephone,
            "contact_email": contact_email,
            "password": password
        }
    
    return None

def profile_completion_form(user_data):
    """Formulaire de complétion de profil après inscription"""
    st.subheader("🖼️ Logo de l'entreprise")
    logo_file = st.file_uploader("Téléverser logo (PNG, JPG)", type=["png", "jpg", "jpeg"])
    
    st.markdown("---")
    st.subheader("🏗️ Projets antérieurs")
    
    # Nombre de projets à ajouter
    nb_projets = st.number_input("Nombre de projets à ajouter", min_value=0, max_value=10, value=0)
    
    projets = []
    
    for i in range(nb_projets):
        with st.expander(f"Projet #{i+1}"):
            col1, col2 = st.columns(2)
            
            with col1:
                nom_projet = st.text_input(f"Nom du projet", key=f"nom_{i}")
                montant = st.number_input(f"Montant ($)", min_value=0, key=f"montant_{i}")
                duree = st.number_input(f"Durée (jours)", min_value=1, key=f"duree_{i}")
            
            with col2:
                specifications = st.text_area(f"Spécifications", key=f"spec_{i}")
                document = st.file_uploader(f"Document PDF", type=["pdf"], key=f"doc_{i}")
            
            if nom_projet:
                projets.append({
                    "nom_projet": nom_projet,
                    "montant": montant,
                    "duree_jours": duree,
                    "specifications": specifications,
                    "document": document
                })
    
    if st.button("💾 Sauvegarder le profil", type="primary"):
        return {
            "logo_file": logo_file,
            "projets": projets
        }
    
    return None