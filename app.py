from flask import Flask, request, jsonify
import pdfplumber
import tempfile
import re
import os

app = Flask(__name__)

def parse_invoice_pdf(file_path):
    produits = []
    with pdfplumber.open(file_path) as pdf:
        texte = ""
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                texte += t + "\n"
    # --- À ADAPTER selon la forme de ta facture ! ---
    # Ici, chaque produit est sur une ligne: "NomProduit    2   34,50" ou "NomProduit    1    22.00"
    pattern = re.compile(r"(.+?)\s+(\d+)\s+([\d,.]+)")
    for match in pattern.finditer(texte):
        nom = match.group(1).strip()
        quantite = int(match.group(2))
        prix_unitaire = float(match.group(3).replace(",", "."))
        produits.append({
            "name": nom,
            "quantity": quantite,
            "unit_price_usd": prix_unitaire  # ou EUR si c’est ta devise
        })
    return produits

@app.route("/api/upload-invoice", methods=["POST"])
def upload_invoice():
    if "invoice_pdf" not in request.files:
        return jsonify({"error": "No PDF uploaded"}), 400
    pdf_file = request.files["invoice_pdf"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp:
        pdf_file.save(temp.name)
        produits = parse_invoice_pdf(temp.name)
    # Tu peux supprimer le fichier temporaire si tu veux :
    os.remove(temp.name)
    return jsonify({
        "filename": pdf_file.filename,
        "parsed_products": produits,
        "message": "Facture analysée avec succès."
    })

if __name__ == "__main__":
    app.run(debug=True)
