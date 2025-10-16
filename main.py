# Health
curl -s https://research-api-5amu.onrender.com/health

# Liste (Sortierung nach Jahr)
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?limit=20&order=year.desc"

# Filter Titel (ILIKE)
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?title=magnesium&limit=10"

# Filter Tag / Outcome (Array-contains)
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?tag=magnesium&limit=10"
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?outcome=blood%20pressure&limit=10"

# Exakt nach DOI oder PMID
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?doi=10.1001/jama.2023.12345"
curl -s -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies?pmid=37900123"

# Upsert EINER Studie (Konfliktspalte wird automatisch gewählt)
curl -s -X POST -H "Content-Type: application/json" -H "X-API-Key: <API_KEY>" \
  "https://research-api-5amu.onrender.com/studies" \
  -d '{
    "doi": "10.1001/jama.2023.12345",
    "pmid": "37900123",
    "year": 2023,
    "study_design": "RCT",
    "n_participants": 412,
    "title": "Effect of Oral Magnesium on Blood Pressure in Adults",
    "journal": "JAMA",
    "abstract": "BACKGROUND ...",
    "outcomes": ["blood pressure","systolic blood pressure","diastolic blood pressure"],
    "tags": ["magnesium","hypertension","supplementation"],
    "source_url": "https://pubmed.ncbi.nlm.nih.gov/37900123/"
  }'
