import uuid
from datetime import datetime

def upload_logo(supabase, file):
    """Upload logo entreprise"""
    try:
        bucket_name = "logos"
        file_ext = file.name.split('.')[-1]
        file_name = f"{uuid.uuid4()}.{file_ext}"
        
        # Upload
        supabase.storage.from_(bucket_name).upload(
            file_name, 
            file.getvalue(),
            file_options={"content-type": file.type}
        )
        
        # URL publique
        return supabase.storage.from_(bucket_name).get_public_url(file_name)
    except Exception as e:
        print(f"Erreur upload logo: {e}")
        return None

def upload_document_projet(supabase, file):
    """Upload document projet"""
    try:
        bucket_name = "documents"
        file_ext = file.name.split('.')[-1]
        file_name = f"projet_{uuid.uuid4()}.{file_ext}"
        
        supabase.storage.from_(bucket_name).upload(
            file_name,
            file.getvalue(),
            file_options={"content-type": file.type}
        )
        
        return supabase.storage.from_(bucket_name).get_public_url(file_name)
    except Exception as e:
        print(f"Erreur upload document: {e}")
        return None

def upload_soumission(supabase, file):
    """Upload soumission PDF"""
    try:
        bucket_name = "soumissions"
        file_ext = file.name.split('.')[-1]
        file_name = f"soumission_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4()}.{file_ext}"
        
        supabase.storage.from_(bucket_name).upload(
            file_name,
            file.getvalue(),
            file_options={"content-type": file.type}
        )
        
        return supabase.storage.from_(bucket_name).get_public_url(file_name)
    except Exception as e:
        print(f"Erreur upload soumission: {e}")
        return None