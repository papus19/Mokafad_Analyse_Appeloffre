import streamlit as st

def signup_form():
    """Formulaire d'inscription avec validation"""
    with st.form("signup_form"):
        st.subheader("Informations de l'entreprise")
        
        col1, col2 = st.columns(2)
        
        with col1:
            nom_entreprise = st.text_input("Nom de l'entreprise *")
            numero_neq = st.text_input("Numéro NEQ *", help="Numéro d'entreprise du Québec (10 chiffres)")
            licence_rbq = st.text_input("Licence RBQ *", help="Numéro de licence de la Régie du bâtiment du Québec")
            
        with col2:
            # CORRECTION #3 : Ajout des nouvelles spécialités résidentielles/commerciales
            specialites = st.multiselect(
                "Spécialités * (Résidentiel & Commercial)",
                options=[
                    "16200 - Électricité",
                    "16400 - Système de sécurité",
                    "15000 - Plomberie",
                    "04200 - Maçonnerie",
                    "06100 - Ébénisterie/Menuiserie",
                    "01000 - Entrepreneur général",
                    "99000 - Autre (préciser dans le profil)",
                    "Résidentiel",
                    "Commercial"
                ],
                default=[],
                help="Sélectionnez toutes les spécialités que vous exercez en résidentiel et/ou commercial"
            )
            adresse = st.text_input("Adresse")
            ville = st.text_input("Ville")
        
        col3, col4 = st.columns(2)
        
        with col3:
            province = st.selectbox("Province", ["Québec", "Ontario", "Nouveau-Brunswick", "Autre"], index=0)
            code_postal = st.text_input("Code postal")
            
        with col4:
            contact_nom = st.text_input("Nom du contact")
            contact_telephone = st.text_input("Téléphone")
        
        st.subheader("Authentification")
        contact_email = st.text_input("Adresse courriel *", help="Servira pour la connexion")
        password = st.text_input("Mot de passe *", type="password", help="Minimum 6 caractères")
        password_confirm = st.text_input("Confirmer le mot de passe *", type="password")
        
        submit = st.form_submit_button("📝 Créer mon compte", use_container_width=False)
        
        if submit:
            # Validation
            if not nom_entreprise or not numero_neq or not licence_rbq or not contact_email or not password:
                st.error("❌ Veuillez remplir tous les champs obligatoires (*)")
                return None
            
            if password != password_confirm:
                st.error("❌ Les mots de passe ne correspondent pas")
                return None
            
            if len(password) < 6:
                st.error("❌ Le mot de passe doit contenir au moins 6 caractères")
                return None
            
            if not specialites:
                st.error("❌ Veuillez sélectionner au moins une spécialité")
                return None
            
            return {
                "nom_entreprise": nom_entreprise,
                "numero_neq": numero_neq,
                "licence_rbq": licence_rbq,
                "specialites": specialites,
                "adresse": adresse,
                "ville": ville,
                "province": province,
                "code_postal": code_postal,
                "pays": "Canada",
                "contact_nom": contact_nom,
                "contact_telephone": contact_telephone,
                "contact_email": contact_email,
                "password": password
            }
    
    return None


def profile_completion_form(user):
    """Formulaire de complétion du profil après inscription"""
    st.info("👋 Bienvenue ! Complétez votre profil pour accéder à l'application.")
    
    with st.form("complete_profile"):
        st.subheader("📸 Logo de l'entreprise")
        logo_file = st.file_uploader(
            "Uploader votre logo (optionnel)",
            type=['png', 'jpg', 'jpeg'],
            help="Format recommandé : PNG carré, max 2MB"
        )
        
        st.subheader("🏗️ Projets antérieurs (optionnel)")
        st.write("Ajoutez vos projets passés pour améliorer la précision des analyses")
        
        nb_projets = st.number_input("Nombre de projets à ajouter", min_value=0, max_value=5, value=0)
        
        projets = []
        for i in range(nb_projets):
            with st.expander(f"Projet {i+1}"):
                col1, col2 = st.columns(2)
                with col1:
                    nom = st.text_input(f"Nom du projet {i+1}", key=f"nom_{i}")
                    montant = st.number_input(f"Montant ($)", min_value=0, value=0, key=f"montant_{i}")
                with col2:
                    duree = st.number_input(f"Durée (jours)", min_value=1, value=30, key=f"duree_{i}")
                    doc = st.file_uploader(f"Document PDF (optionnel)", type=['pdf'], key=f"doc_{i}")
                
                specs = st.text_area(f"Spécifications", key=f"specs_{i}")
                
                if nom:
                    projets.append({
                        "nom_projet": nom,
                        "montant": montant,
                        "duree_jours": duree,
                        "specifications": specs,
                        "document": doc
                    })
        
        submit = st.form_submit_button("✅ Terminer la configuration", use_container_width=False)
        
        if submit:
            return {
                "logo_file": logo_file,
                "projets": projets
            }
    
    return None
