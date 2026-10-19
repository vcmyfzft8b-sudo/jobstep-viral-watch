// The demo's made-up person per language: a weak "before" CV (vague, no numbers, mixed date formats, a cliché
// objective – the kind of CV a JobStep video starts with) and the job ad pasted at the job step.
// `node samples.mjs` writes assets/cv-<lang>.pdf.

export const SAMPLES = {
  fr: {
    file: "CV_Camille_Laurent.pdf",
    name: "Camille Laurent",
    role: "Étudiante en communication",
    contact: ["camille.laurent@example.com", "06 12 34 56 78", "Lyon"],
    labels: { profile: "Objectif", experience: "Expériences", education: "Formation", skills: "Compétences", languages: "Langues", hobbies: "Loisirs" },
    profile:
      "Je suis une personne motivée, dynamique et sérieuse. Je cherche un poste dans une entreprise où je pourrai évoluer et mettre en avant mes qualités.",
    experience: [
      { title: "Stage marketing", place: "Maison Arôme, Lyon", dates: "Sept 2024 - 02/2025", bullets: ["Aide sur les réseaux sociaux", "Création de posts", "Différentes tâches administratives"] },
      { title: "Vendeuse", place: "Boutique Lin & Coton", dates: "2023 - 2024", bullets: ["Accueil des clients", "Caisse et rangement", "Travail en équipe"] },
      { title: "Baby-sitting", place: "Particuliers", dates: "été 2022", bullets: ["Garde d'enfants"] },
    ],
    education: [{ title: "Licence Information-Communication", place: "Université Lumière Lyon 2", dates: "2022 - 2025" }, { title: "Bac ES", place: "Lycée Ampère", dates: "2022" }],
    skills: ["Word", "Excel", "Instagram", "Canva", "Sérieuse", "Ponctuelle"],
    languages: ["Anglais : bien", "Espagnol : notions"],
    hobbies: "Voyages, cuisine, cinéma",
    job: `Assistant(e) Marketing Digital (H/F) – CDI – Lyon
Atelier Nova, marque lyonnaise de décoration en ligne, recrute un(e) assistant(e) marketing digital.
Missions :
- Gérer les réseaux sociaux (Instagram, TikTok, LinkedIn) et le calendrier éditorial
- Créer des visuels et des vidéos courtes avec Canva
- Suivre les KPI et préparer le reporting hebdomadaire
- Participer aux campagnes emailing (Brevo) et à la mise à jour du site Shopify
Profil :
- Bac+3 en marketing ou communication, première expérience (stage ou alternance)
- Maîtrise d'Excel et de Google Analytics
- Anglais professionnel, sens de l'organisation et esprit d'équipe`,
  },
  es: {
    file: "CV_Lucia_Martin.pdf",
    name: "Lucía Martín Gómez",
    role: "Recién graduada en Marketing",
    contact: ["lucia.martin@example.com", "612 345 678", "Madrid"],
    labels: { profile: "Objetivo", experience: "Experiencia", education: "Formación", skills: "Habilidades", languages: "Idiomas", hobbies: "Aficiones" },
    profile:
      "Soy una persona responsable, trabajadora y con muchas ganas de aprender. Busco un puesto en una empresa donde pueda crecer profesionalmente.",
    experience: [
      { title: "Prácticas de marketing", place: "Agencia Brisa Digital, Madrid", dates: "Sept 2024 - 02/2025", bullets: ["Ayuda con las redes sociales", "Hacer publicaciones", "Tareas administrativas varias"] },
      { title: "Dependienta", place: "Tienda Olivo", dates: "2023 - 2024", bullets: ["Atención al cliente", "Caja y reposición", "Trabajo en equipo"] },
      { title: "Monitora de campamento", place: "Campamento de verano", dates: "verano 2022", bullets: ["Cuidado de niños"] },
    ],
    education: [{ title: "Grado en Marketing", place: "Universidad Complutense de Madrid", dates: "2021 - 2025" }, { title: "Bachillerato", place: "IES Cervantes", dates: "2021" }],
    skills: ["Word", "Excel", "Instagram", "Canva", "Responsable", "Puntual"],
    languages: ["Inglés: bien", "Francés: básico"],
    hobbies: "Viajar, cocinar, cine",
    job: `Asistente de Marketing Digital – Madrid – Contrato indefinido
Casa Alba, marca española de decoración online, busca asistente de marketing digital.
Funciones:
- Gestionar las redes sociales (Instagram, TikTok, LinkedIn) y el calendario de contenidos
- Crear diseños y vídeos cortos con Canva
- Hacer seguimiento de los KPI y preparar el informe semanal
- Apoyar las campañas de email marketing (Mailchimp) y actualizar la tienda online en Shopify
Requisitos:
- Grado en Marketing, Publicidad o similar, experiencia previa en prácticas
- Excel y Google Analytics
- Inglés B2, organización y trabajo en equipo`,
  },
  sl: {
    // a real LinkedIn job post (Forward, Ljubljana), pasted by its link at the job step like in the JobStep videos
    jobLink: "https://www.linkedin.com/jobs/view/4474038171",
    file: "CV_Nina_Kovac.pdf",
    name: "Nina Kovač",
    role: "Študentka komunikologije",
    contact: ["nina.kovac@example.com", "041 234 567", "Ljubljana"],
    labels: { profile: "Cilj", experience: "Delovne izkušnje", education: "Izobrazba", skills: "Znanja", languages: "Jeziki", hobbies: "Hobiji" },
    profile:
      "Sem odgovorna, komunikativna in delovna oseba. Iščem zaposlitev v podjetju, kjer se bom lahko razvijala in pokazala svoje sposobnosti.",
    experience: [
      { title: "Praksa v marketingu", place: "Agencija Sončnica, Ljubljana", dates: "sept. 2024 - 02/2025", bullets: ["Pomoč pri družbenih omrežjih", "Pripravljanje objav", "Razna administrativna dela"] },
      { title: "Študentsko delo – prodajalka", place: "Trgovina Lipa", dates: "2023 - 2024", bullets: ["Delo s strankami", "Blagajna in zlaganje blaga", "Delo v ekipi"] },
      { title: "Varstvo otrok", place: "Zasebno", dates: "poletje 2022", bullets: ["Varovanje otrok"] },
    ],
    education: [{ title: "Komunikologija (UN)", place: "Fakulteta za družbene vede, Univerza v Ljubljani", dates: "2022 - 2025" }, { title: "Splošna matura", place: "Gimnazija Bežigrad", dates: "2022" }],
    skills: ["Word", "Excel", "Instagram", "Canva", "Zanesljiva", "Točna"],
    languages: ["Angleščina: dobro", "Nemščina: osnove"],
    hobbies: "Potovanja, kuhanje, film",
    job: `Asistent/ka za digitalni marketing – Ljubljana – redna zaposlitev
Studio Breza, slovenska spletna blagovna znamka za dom, išče asistenta/ko za digitalni marketing.
Naloge:
- upravljanje družbenih omrežij (Instagram, TikTok, LinkedIn) in vsebinskega koledarja
- priprava grafik in kratkih videov v Canvi
- spremljanje KPI in tedensko poročanje
- pomoč pri e-poštnih kampanjah (Mailchimp) in urejanju spletne trgovine Shopify
Pričakujemo:
- VI. ali VII. stopnjo izobrazbe (marketing, komunikologija), prve izkušnje (praksa, študentsko delo)
- znanje Excela in Google Analytics
- angleščino, organiziranost in timski duh`,
  },
};

/** A two-column "made in Canva" CV: coloured side bar with initials, contact, skills and languages. */
export function cvHtml(s) {
  const initials = s.name.split(" ").slice(0, 2).map((w) => w[0]).join("");
  const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const block = (e) => `<div class="item"><div class="row"><b>${esc(e.title)}</b><span>${esc(e.dates)}</span></div>
    <div class="place">${esc(e.place)}</div>${e.bullets ? `<ul>${e.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}</div>`;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  @page{size:A4;margin:0} body{margin:0;font-family:"Helvetica Neue",Arial,sans-serif;color:#2b2b2b}
  .page{display:flex;width:210mm;height:297mm}
  .side{width:72mm;background:#e9e1d6;padding:16mm 9mm;box-sizing:border-box}
  .main{flex:1;padding:16mm 12mm;box-sizing:border-box}
  .avatar{width:34mm;height:34mm;border-radius:50%;background:#b9a48c;color:#fff;font-size:30pt;display:flex;align-items:center;justify-content:center;margin:0 auto 9mm;letter-spacing:1px}
  h1{font-family:Georgia,serif;font-weight:400;font-size:27pt;margin:0 0 2mm;letter-spacing:.5px}
  .role{font-size:11pt;color:#8a7560;text-transform:uppercase;letter-spacing:2px;margin-bottom:9mm}
  h2{font-size:10.5pt;text-transform:uppercase;letter-spacing:2.5px;color:#8a7560;border-bottom:1px solid #cdbfae;padding-bottom:1.5mm;margin:7mm 0 3mm}
  .side h2{margin-top:0}
  .side p,.side li{font-size:9.5pt;line-height:1.55;margin:0}
  .side ul{list-style:none;padding:0;margin:0 0 7mm}
  .main p{font-size:10pt;line-height:1.6;margin:0}
  .item{margin-bottom:4.5mm}.row{display:flex;justify-content:space-between;font-size:10.5pt}.row span{color:#8a7560;font-size:9pt}
  .place{font-size:9.5pt;color:#6b6b6b;margin:.5mm 0 1mm;font-style:italic}
  .item ul{margin:0;padding-left:5mm}.item li{font-size:9.5pt;line-height:1.5}
  </style></head><body><div class="page">
  <div class="side"><div class="avatar">${initials}</div>
    <h2>Contact</h2><ul>${s.contact.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    <h2>${s.labels.skills}</h2><ul>${s.skills.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    <h2>${s.labels.languages}</h2><ul>${s.languages.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
    <h2>${s.labels.hobbies}</h2><p>${esc(s.hobbies)}</p></div>
  <div class="main"><h1>${esc(s.name)}</h1><div class="role">${esc(s.role)}</div>
    <h2>${s.labels.profile}</h2><p>${esc(s.profile)}</p>
    <h2>${s.labels.experience}</h2>${s.experience.map(block).join("")}
    <h2>${s.labels.education}</h2>${s.education.map(block).join("")}</div>
  </div></body></html>`;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { chromium } = await import("playwright");
  const fs = await import("node:fs");
  const path = await import("node:path");
  const dir = path.join(path.dirname(new URL(import.meta.url).pathname), "assets");
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage();
  for (const [lang, s] of Object.entries(SAMPLES)) {
    await page.setContent(cvHtml(s));
    await page.pdf({ path: path.join(dir, s.file), format: "A4", printBackground: true });
    console.log(`wrote assets/${s.file}`);
  }
  await browser.close();
}
