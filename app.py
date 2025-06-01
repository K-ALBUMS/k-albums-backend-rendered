import pdfplumber
import re

def get_full_text_lines(file_path):
    """
    Ouvre le PDF avec pdfplumber, extrait tout le texte page par page,
    puis renvoie une liste de lignes (déjà strip()).
    """
    with pdfplumber.open(file_path) as pdf:
        all_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                for line in text.split("\n"):
                    cleaned = line.strip()
                    if cleaned:
                        all_text.append(cleaned)
    return all_text

def parse_products_from_lines(lines_list):
    """
    Analyse une liste de lignes extraites d'un PDF (pdfplumber) et retourne
    une liste de produits sous forme de dicts :
      - name            : string
      - release_date    : string ("YYYY-MM-DD", "YYYY-MM", "YYYY" ou "N/A")
      - quantity        : int
      - unit_price_usd  : float

    lines_list doit déjà être "strip()"ée (pas de \n en fin de ligne).
    On part du principe que la section produits commence dès qu'on trouve
    l'en-tête "Product Quantity Price Total" et s'arrête à "Subtotal".
    """

    products = []
    i = 0
    n = len(lines_list)

    # 1. Repérer le début de la section produits
    while i < n and "Product Quantity Price Total" not in lines_list[i]:
        i += 1

    # Si on n'a pas trouvé l'en-tête, on renvoie liste vide
    if i >= n:
        return []

    # Passer la ligne d'en-tête
    i += 1

    # 2. Parcourir jusqu'à "Subtotal"
    def is_subtotal_line(line):
        return line.strip().startswith("Subtotal")

    # Regex pour extraire date (YYYY, YYYY-MM ou YYYY-MM-DD)
    date_pattern = re.compile(r"(\d{4}(?:-\d{2}(?:-\d{2})?)?)")

    # Regex pour extraire quantité + prix unitaire (ex : "2 $39.85" ou "10 $6.78")
    qty_price_pattern = re.compile(r"(\d+)\s*\$?([\d.,]+)")

    while i < n and not is_subtotal_line(lines_list[i]):
        # 2.1. Accumuler le nom du produit jusqu'à la ligne commençant par "Release"
        name_lines = []
        while i < n and not lines_list[i].strip().startswith("Release"):
            text = lines_list[i].strip()
            if text and not text.startswith("Product Quantity Price Total"):
                name_lines.append(text)
            i += 1

        if i >= n:
            break

        # On est sur une ligne "Release : ..."
        release_line = lines_list[i].strip()
        i += 1  # on passera à la ligne suivante pour récupérer quantité/prix si besoin

        full_name = " ".join(name_lines).strip()

        # 2.2. Extraire la date au sein de la ligne "Release :"
        release_date = "N/A"
        quantity = None
        unit_price = None

        after_release = release_line[len("Release :"):].strip()

        # 2.2.1. Chercher une date valide
        date_match = date_pattern.match(after_release)
        if date_match:
            release_date = date_match.group(1)
            rest = after_release[date_match.end():].strip()
        else:
            rest = after_release

        # 2.2.2. Tenter d'extraire quantité + prix sur la même ligne
        same_line_match = qty_price_pattern.search(rest)
        if same_line_match:
            quantity = int(same_line_match.group(1))
            unit_price = float(same_line_match.group(2).replace(",", "."))
        else:
            # 2.2.3. Sinon, regarder la ligne suivante pour qty/prix
            if i < n:
                next_line = lines_list[i].strip()
                if next_line.startswith("Release"):
                    i += 1
                    if i < n:
                        next_line = lines_list[i].strip()
                    else:
                        next_line = ""
                qty_price_match = qty_price_pattern.search(next_line)
                if qty_price_match:
                    quantity = int(qty_price_match.group(1))
                    unit_price = float(qty_price_match.group(2).replace(",", "."))
                    i += 1
                else:
                    qty_price_match2 = qty_price_pattern.search(next_line)
                    if qty_price_match2:
                        quantity = int(qty_price_match2.group(1))
                        unit_price = float(qty_price_match2.group(2).replace(",", "."))
                        i += 1

        # Valeurs par défaut si non trouvées
        if quantity is None:
            quantity = 0
        if unit_price is None:
            unit_price = 0.0

        products.append({
            "name": full_name,
            "release_date": release_date if release_date else "N/A",
            "quantity": quantity,
            "unit_price_usd": round(unit_price, 2)
        })

    return products

if __name__ == "__main__":
    invoice_pdf_path = "invoice-46584.pdf"  # Remplacez par votre chemin de fichier
    lines = get_full_text_lines(invoice_pdf_path)
    produits = parse_products_from_lines(lines)

    for idx, prod in enumerate(produits, 1):
        print(f"{idx:02d}. {prod['name']}")
        print(f"     → Date   : {prod['release_date']}")
        print(f"     → Quantité : {prod['quantity']}")
        print(f"     → Prix U.  : {prod['unit_price_usd']} USD\n")

    print(f"Nombre total de produits extraits : {len(produits)}")
