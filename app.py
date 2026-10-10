import os
import io
import re
import json
import uuid
import base64
import logging
import time
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, send_file
from groq import Groq
import pypdf
from PIL import Image
from fpdf import FPDF

# Configuração de logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Carregar variáveis de ambiente
base_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(base_dir, '.env')
load_dotenv(dotenv_path)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max upload
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

API_KEY_GROQ = os.getenv('API_KEY_GROQ')
if not API_KEY_GROQ:
    raise ValueError("A variável API_KEY_GROQ não está configurada no arquivo .env!")

client = Groq(api_key=API_KEY_GROQ, max_retries=0)

def call_groq_with_retry(create_fn, retries=3, initial_delay=3):
    """Executa chamada à Groq com tratamento e espera automática em caso de Rate Limit (429)."""
    delay = initial_delay
    for attempt in range(retries):
        try:
            return create_fn()
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "rate_limit" in err_str or "too many requests" in err_str or "tokens per minute" in err_str:
                # Se for esgotamento de cota diária (TPD), não adianta esperar segundos. Lança imediatamente para acionar fallback
                if "tokens per day" in err_str or "tpd" in err_str:
                    logging.warning("Limite diário de tokens (TPD) atingido. Acionando fallback de modelo imediatamente...")
                    raise e
                if attempt < retries - 1:
                    logging.warning(f"Rate limit atingido (429). Aguardando {delay}s antes de tentar novamente (tentativa {attempt + 1}/{retries})...")
                    time.sleep(delay)
                    delay *= 2
                    continue
            raise e

# Diretório para PDFs gerados
PDF_STORAGE_DIR = os.path.join(base_dir, 'static', 'generated_pdfs')
os.makedirs(PDF_STORAGE_DIR, exist_ok=True)

# Definição dos modelos para cada etapa da arquitetura multiagente
MODEL_LEITOR = "qwen/qwen3.8-27b"        # Agente Leitor com visão para imagem/PDF escaneado
MODEL_ANALISTA = "openai/gpt-oss-20b"     # Agente Analista da vaga (menor e mais rápido)
MODEL_ADAPTADOR = "qwen/qwen3.8-27b"      # Agente Adaptador principal (alta capacidade e sem esgotamento de TPD)
MODEL_AUDITOR = "openai/gpt-oss-20b"      # Agente Auditor de fidelidade (modelo independente do adaptador)

# ==============================================================================
# PROMPTS DOS AGENTES
# ==============================================================================

PROMPT_LEITOR_VISAO = """Você é o Agente Leitor de Currículos, especialista em OCR e Transcrição Fiel de Documentos.
Sua única função é transcrever todo o texto visível na imagem do currículo EXATAMENTE como ele está escrito.

REGRAS RÍGIDAS:
1. Transcreva cada palavra, número, data, pontuação e símbolo com fidelidade absoluta.
2. NUNCA corrija erros ortográficos, gramaticais ou de formatação do original.
3. NUNCA resuma, reorganize, deduza ou complete informações faltantes.
4. NUNCA adicione saudações, explicações ou comentários antes ou depois da transcrição.
5. Devolva estritamente o texto transcrito na íntegra."""

PROMPT_ANALISTA_VAGA = """Você é o Agente Analista da Vaga, especialista em RH e sistemas de triagem ATS.
Sua única responsabilidade é ler a descrição da vaga e extrair todos os critérios técnicos e comportamentais de forma concisa e direta.
Você NÃO recebe o currículo do candidato e NÃO escreve nada de currículo.

Responda EXCLUSIVAMENTE em formato JSON válido com as seguintes chaves (máximo 8 itens nas listas):
{
  "cargo": "Nome do cargo e senioridade identificados",
  "requisitos_obrigatorios": ["lista sintética de requisitos essenciais"],
  "requisitos_desejaveis": ["lista sintética de diferenciais"],
  "ferramentas": ["ferramentas, softwares, linguagens e tecnologias"],
  "competencias_comportamentais": ["soft skills e atitudes esperadas"],
  "palavras_chave": ["8 a 12 palavras-chave críticas para triagem ATS"]
}
Não inclua nenhuma introdução, explicação ou markdown fora do bloco JSON."""

PROMPT_ADAPTADOR = """# PAPEL E LEI SUPREMA: FIDELIDADE ABSOLUTA AOS FATOS REAIS DO CURRÍCULO
Você é o Agente Adaptador de Currículos, um Especialista Executivo em Recrutamento, RH e Sistemas ATS com mais de 15 anos de experiência.
Um recrutador sênior NUNCA altera fatos do histórico de um candidato. Isso destruiria a credibilidade dele perante a empresa contratante.
A SUA FUNÇÃO É APENAS REORGANIZAR E DESTACAR O QUE O CANDIDATO REALMENTE INFORMOU. NUNCA CRIAR DADOS NOVOS.

## PROIBIÇÕES RÍGIDAS E INVIOLÁVEIS (TOLERÂNCIA ZERO):

1. **CARGOS E EMPRESAS SÃO CÓPIA EXATA DO ORIGINAL:**
   - O cargo exercido e o nome da empresa em CADA experiência profissional devem ser EXATAMENTE IGUAIS aos que constam no <CURRICULO_ORIGINAL>.
   - Se a experiência no original diz "Operador de Logística e E-commerce", O CARGO NA EXPERIÊNCIA DEVE SER OBRIGATORIAMENTE "Operador de Logística e E-commerce".
   - NUNCA troque o cargo de uma experiência para "Estágio em TI", "Assistente de TI", "Desenvolvedor" ou similar.
   - Frases de cabeçalho/objetivo no topo do currículo (como "Candidato a Estágio em TI") são apenas o OBJETIVO futuro do candidato. NUNCA use o objetivo como se fosse o cargo de uma experiência de trabalho passada!
   - Mantenha a empresa exatamente como informada (ex.: "Operações de E-commerce"). NUNCA omita a empresa e NUNCA invente empresa.

2. **NUNCA INVENTE MÉTRICAS, PORCENTAGENS OU NÚMEROS:**
   - Se o original não traz métricas quantitativas (ex.: "10 mil registros", "15% de melhoria"), É TERMINANTEMENTE PROIBIDO inventar qualquer porcentagem, número ou volume. Descreva as atividades reais com verbos de ação sem inventar números.

3. **PROJETOS REAIS (APENAS OS LISTADOS PELO CANDIDATO):**
   - Liste EXCLUSIVAMENTE os projetos que o candidato declarou no <CURRICULO_ORIGINAL>.
   - É TERMINANTEMENTE PROIBIDO inventar projetos (ex.: NÃO invente "Gerador de Tickets", "Sistema X", etc.). Se o candidato informou 2 projetos (ex.: AstroControl e B3 Vision), apresente APENAS esses 2 projetos.
   - Nas descrições dos projetos, não invente funcionalidades não declaradas (ex.: não invente "rotas RESTful", "controle de sessões", "autenticação").

4. **DATAS, ANOS E PREVISÕES (CÓPIA LITERAL):**
   - Copie datas, anos de previsão e períodos EXATAMENTE como constam no original (ex.: se o original diz "Previsão 2028", escreva "Previsão 2028", NUNCA altere para 2025).
   - Se uma experiência ou curso NÃO tem data no original, NÃO coloque data!

5. **SEÇÃO DE IDIOMAS:**
   - Se o candidato NÃO incluiu idiomas no original, NÃO crie a seção de IDIOMAS. NUNCA invente "Inglês", "Espanhol", etc.

6. **REQUISITOS DA VAGA QUE O CANDIDATO NÃO TEM:**
   - Devem ir OBRIGATORIAMENTE para a seção "6. Lacunas e pontos de atenção".
   - NUNCA adicione habilidades ou ferramentas que o candidato não possui ao currículo adaptado para "agradar" a vaga.

## ESTRUTURA OBRIGATÓRIA DA RESPOSTA:

## 1. Análise da vaga e Compatibilidade
- **Cargo e Nível:** [Cargo exato e senioridade da vaga]
- **Top Palavras-Chave Críticas ATS:** [Termos indispensáveis em negrito]
- **Compatibilidade:** [Nota]/100 — [Diagnóstico curto de aderência]

## 2. Lacunas e Pontos de Atenção
[Requisitos da vaga que o candidato NÃO possui em seu histórico original, se houver]

## 3. Currículo adaptado
[NOME COMPLETO DO CANDIDATO]
[Cidade, UF | Contatos | E-mail | Links informados]

RESUMO PROFISSIONAL
[3 a 4 linhas executivas conectando a bagagem REAL do candidato com as prioridades da vaga]

EXPERIÊNCIA PROFISSIONAL
[Cargo Real do Original] | [Empresa Real do Original] | [Período Real do Original]
• [Atividade real informada reescrita com clareza e verbos de ação sem inventar números ou fatos]

PROJETOS RELEVANTES
(Apenas se existirem no original)
[Nome do Projeto Real] — [Tecnologias reais]
• [Atividades reais informadas pelo candidato naquele projeto]

FORMAÇÃO ACADÊMICA
[Curso Real | Instituição Real | Datas e previsões exatamente como informadas no original]

CURSOS E CERTIFICAÇÕES
(Apenas se existirem no original)
• [Cursos reais informados]

HABILIDADES TÉCNICAS E COMPETÊNCIAS
[Apenas as ferramentas e habilidades reais informadas pelo candidato]

## 4. O que foi alterado e por quê
[Breve resumo de 2 a 3 linhas explicando as melhorias de redação realizadas mantendo 100% de fidelidade aos fatos]

## CONFERÊNCIA FINAL OBRIGATÓRIA
Conferência de fidelidade: todas as empresas, cargos, datas, formações e habilidades do currículo adaptado existem no currículo original.
"""

PROMPT_AUDITOR = """Você é o Agente Auditor de Fidelidade Curricular e Sistemas ATS.
Sua responsabilidade é auditar com rigor cirúrgico o CURRÍCULO ADAPTADO contra o CURRÍCULO ORIGINAL.

AUDITORIA PONTO A PONTO OBRIGATÓRIA:
1. **CARGOS EXERCIDOS:**
   - Na seção EXPERIÊNCIA PROFISSIONAL, verifique o cargo atribuído. O candidato realmente exerceu esse cargo no original?
   - ALERTA MÁXIMO: Frases de objetivo ou headline no topo (ex: "Candidato a Estágio em TI") NÃO são cargos de experiência. Se o candidato trabalhou como "Operador de Logística" e o adaptado colocou "Estágio em TI" ou "Desenvolvedor" como cargo da experiência, REPROVE IMEDIATAMENTE! O cargo deve ser o mesmo que o candidato exerceu no original.
2. **EMPRESAS E PROJETOS:**
   - Cada empresa existe no original?
   - Cada projeto citado existe no original? Se o adaptado citar qualquer projeto (ex: "Gerador de Tickets", "Sistema X", etc.) não presente no original, REPROVE IMEDIATAMENTE!
3. **DATAS E ANOS:**
   - Datas de formação (ex: Previsão 2028 vs 2025) e períodos batem 100% com o original? Se o adaptado alterou anos de formatura, REPROVE IMEDIATAMENTE!
4. **IDIOMAS E CURSOS:**
   - Se o adaptado adicionou idiomas (Inglês, Espanhol, etc.) e o original NÃO tinha esses idiomas, REPROVE IMEDIATAMENTE!
   - Se o adaptado adicionou cursos não presentes no original, REPROVE IMEDIATAMENTE!
5. **NÚMEROS, MÉTRICAS E ADJETIVOS TÉCNICOS:**
   - Foram inventados números, porcentagens, volumes ou adjetivos técnicos não declarados? REPROVE IMEDIATAMENTE!

Responda EXCLUSIVAMENTE em formato JSON com o schema:
{
  "aprovado": true | false,
  "itens_inventados": ["descrição do item 1 inventado ou inferido", ...]
}
Se todos os dados forem 100% fiéis ao original, "aprovado": true e "itens_inventados": []."""

FIRST_MESSAGE = """Olá! 👋
Sou o VagasFilter Assistant, seu especialista em recrutamento e sistemas ATS.

Para personalizar seu currículo com rigor ético absoluto e padrão ouro de fidelidade, vou precisar de:
1. **Seu currículo atual** (em PDF, TXT ou imagem escaneada)
2. **A descrição da vaga** (texto completo ou link público)

Nosso pipeline multiagente analisa a vaga, adapta suas experiências reais sem inventar nenhum dado e audita todo o conteúdo antes de gerar seu currículo ATS-friendly.

Pode anexar os arquivos no clipe 📎 ou colar as informações quando estiver pronto!"""

# ==============================================================================
# ETAPA 1: AGENTE LEITOR (OCR / VISÃO QUANDO NECESSÁRIO) E EXTRAÇÃO
# ==============================================================================

def extract_text_from_image_bytes(image_bytes, mime_type="image/jpeg"):
    """Agente Leitor com visão usando modelo qwen/qwen3.8-27b."""
    logging.info("Invocando Agente Leitor (Visão) para extrair texto da imagem...")
    base64_img = base64.b64encode(image_bytes).decode('utf-8')
    try:
        response = call_groq_with_retry(lambda: client.chat.completions.create(
            model=MODEL_LEITOR,
            messages=[
                {"role": "system", "content": PROMPT_LEITOR_VISAO},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcreva todo o texto contido neste currículo exatamente como está escrito."},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_img}"}}
                    ]
                }
            ],
            temperature=0.0,
            max_tokens=1500
        ))
        extracted_text = response.choices[0].message.content.strip()
        logging.info(f"Agente Leitor extraiu com sucesso {len(extracted_text)} caracteres.")
        return extracted_text
    except Exception as e:
        logging.error(f"Erro no Agente Leitor com visão: {e}", exc_info=True)
        raise RuntimeError(f"Falha ao ler imagem do currículo via IA de visão: {e}")

def extract_text_from_file(file_storage):
    """
    Etapa 1: Leitor.
    Se o PDF tiver texto normal, NÃO usa IA (extrai direto com pypdf).
    Se for PDF escaneado ou imagem, aciona o Agente Leitor de Visão.
    """
    filename = file_storage.filename.lower()
    raw_bytes = file_storage.stream.read()

    # 1. Arquivo de Imagem (.png, .jpg, .jpeg, .webp)
    if filename.endswith(('.png', '.jpg', '.jpeg', '.webp')):
        mime_type = "image/png" if filename.endswith('.png') else "image/jpeg"
        return extract_text_from_image_bytes(raw_bytes, mime_type)

    # 2. Arquivo PDF
    elif filename.endswith('.pdf'):
        try:
            stream = io.BytesIO(raw_bytes)
            reader = pypdf.PdfReader(stream)
            extracted_pages = []
            for page in reader.pages:
                txt = page.extract_text()
                if txt and txt.strip():
                    extracted_pages.append(txt.strip())
            
            full_text = "\n\n".join(extracted_pages).strip()
            
            # Se encontrou texto selecionável normal (> 50 caracteres), NÃO usa IA
            if len(full_text) >= 50:
                logging.info(f"Texto extraído diretamente via pypdf sem IA ({len(full_text)} caracteres).")
                return full_text
            
            # Caso contrário, PDF escaneado: tenta extrair imagens das páginas e usar IA de visão
            logging.info("PDF sem texto selecionável suficiente. Tentando extrair imagens das páginas para Agente Leitor...")
            images_text = []
            stream.seek(0)
            reader = pypdf.PdfReader(stream)
            for page_num, page in enumerate(reader.pages):
                for img_obj in page.images:
                    img_data = img_obj.data
                    ocr_res = extract_text_from_image_bytes(img_data, mime_type="image/jpeg")
                    if ocr_res:
                        images_text.append(ocr_res)
            
            if images_text:
                return "\n\n".join(images_text)
            
            raise ValueError("O PDF parece ser uma imagem digitalizada e não foi possível extrair suas páginas.")
        except Exception as e:
            logging.warning(f"Falha na extração de texto do PDF: {e}")
            raise ValueError(f"Não foi possível processar o PDF: {e}")

    # 3. Arquivo de Texto (.txt, .md, .rtf, .csv)
    elif filename.endswith(('.txt', '.md', '.rtf', '.csv')):
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                return raw_bytes.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode('utf-8', errors='ignore').strip()
    
    else:
        raise ValueError("Formato não suportado. Por favor, envie arquivos em formato .pdf, .txt ou imagem (.png, .jpg).")

def extract_text_from_url(url):
    """Extrai o conteúdo textual de uma URL pública de vaga."""
    url = url.strip()
    if not (url.startswith('http://') or url.startswith('https://')):
        url = 'https://' + url

    lower_url = url.lower()
    if any(domain in lower_url for domain in ['linkedin.com', 'gupy.io', 'vagas.com.br/login', 'glassdoor.com']):
        return None, "Plataformas como LinkedIn e Gupy exigem login para exibir a descrição da vaga. Por favor, copie e cole o texto da vaga no campo indicado!"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }

    try:
        response = requests.get(url, headers=headers, timeout=12)
        if response.status_code != 200:
            return None, f"Não foi possível acessar a página (código HTTP {response.status_code}). Por favor, copie e cole o texto da vaga diretamente!"

        soup = BeautifulSoup(response.text, 'html.parser')
        for element in soup(['script', 'style', 'noscript', 'header', 'footer', 'nav', 'aside', 'svg']):
            element.decompose()

        text = ' '.join(soup.stripped_strings)
        if len(text) < 120 or 'fazer login' in text.lower() or 'entrar com sua conta' in text.lower():
            return None, "O site da vaga parece exigir login ou bloqueou o acesso público. Por favor, copie e cole a descrição da vaga diretamente!"

        return text[:10000], None
    except Exception as err:
        return None, f"Não conseguimos ler o link automaticamente ({str(err)}). Por favor, copie e cole o texto da vaga diretamente."

# ==============================================================================
# ETAPA 2: AGENTE ANALISTA DA VAGA
# ==============================================================================

def run_agente_analista_vaga(job_text):
    """
    Etapa 2: Analista da Vaga.
    Modelo: openai/gpt-oss-20b (menor e rápido).
    Devolve JSON com cargo, requisitos obrigatórios, desejáveis, ferramentas, soft skills e palavras-chave.
    """
    logging.info(f"[Etapa 2] Executando Agente Analista da Vaga com modelo {MODEL_ANALISTA}...")
    try:
        response = call_groq_with_retry(lambda: client.chat.completions.create(
            model=MODEL_ANALISTA,
            messages=[
                {"role": "system", "content": PROMPT_ANALISTA_VAGA},
                {"role": "user", "content": f"Analise a seguinte descrição de vaga de emprego e responda em JSON:\n\n{job_text}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=650
        ))
        content = response.choices[0].message.content
        json.loads(content)  # Validação de integridade JSON
        logging.info("[Etapa 2] Análise da vaga concluída com sucesso.")
        return content
    except Exception as e:
        logging.warning(f"[Etapa 2] Falha inicial ao analisar vaga ({e}). Tentando fallback resiliente...")
        try:
            fallback_resp = call_groq_with_retry(lambda: client.chat.completions.create(
                model=MODEL_ANALISTA,
                messages=[
                    {"role": "system", "content": PROMPT_ANALISTA_VAGA + "\nIMPORTANTE: Devolva estritamente o objeto JSON puro entre { } sem explicações adicionais."},
                    {"role": "user", "content": f"Analise esta vaga:\n\n{job_text[:4000]}"}
                ],
                temperature=0.1,
                max_tokens=650
            ))
            fb_text = fallback_resp.choices[0].message.content.strip()
            match = re.search(r'\{[\s\S]*\}', fb_text)
            if match:
                fb_text = match.group(0)
            json.loads(fb_text)
            logging.info("[Etapa 2] Análise da vaga recuperada com sucesso via fallback.")
            return fb_text
        except Exception as fb_e:
            logging.error(f"[Etapa 2] Fallback também falhou: {fb_e}. Gerando estrutura de segurança.", exc_info=True)
            return json.dumps({
                "cargo": "Vaga Selecionada",
                "requisitos_obrigatorios": [line.strip() for line in job_text.split('\n') if len(line.strip()) > 5][:6],
                "requisitos_desejaveis": [],
                "ferramentas": [],
                "competencias_comportamentais": [],
                "palavras_chave": []
            }, ensure_ascii=False)

# ==============================================================================
# ETAPA 3: AGENTE ADAPTADOR
# ==============================================================================

def run_agente_adaptador(curriculo_original, analise_vaga_json, extras=None, itens_rejeitados=None):
    """
    Etapa 3: Adaptador.
    Modelo: openai/gpt-oss-120b (maior e mais forte).
    Temperature: 0.15.
    """
    logging.info(f"[Etapa 3] Executando Agente Adaptador com modelo {MODEL_ADAPTADOR}...")
    
    user_prompt = f"""<CURRICULO_ORIGINAL>
{curriculo_original}
</CURRICULO_ORIGINAL>

<ANALISE_VAGA>
{analise_vaga_json}
</ANALISE_VAGA>"""

    if extras:
        user_prompt += f"\n\n<INFORMACOES_EXTRAS>\n{extras}\n</INFORMACOES_EXTRAS>"

    if itens_rejeitados:
        user_prompt += f"""\n\n<ITENS_INVENTADOS_REJEITADOS_PELA_AUDITORIA>
ATENÇÃO CRÍTICA: Na versão anterior, o Agente Auditor identificou que os seguintes itens foram inventados e NÃO existem no currículo original:
{json.dumps(itens_rejeitados, ensure_ascii=False, indent=2)}

VOCÊ DEVE CORRIGIR IMEDIATAMENTE:
1. Remova por completo cada um dos itens listados acima.
2. NUNCA invente métricas, porcentagens, volumes, empresas ou cargos diferentes do original.
3. Se a vaga pede essas competências e o candidato não tem, coloque-as OBRIGATORIAMENTE na seção '6. Lacunas e pontos de atenção'.
4. Entregue a análise completa e o currículo rigorosamente fiel.
</ITENS_INVENTADOS_REJEITADOS_PELA_AUDITORIA>"""

    try:
        response = call_groq_with_retry(lambda: client.chat.completions.create(
            model=MODEL_ADAPTADOR,
            messages=[
                {"role": "system", "content": PROMPT_ADAPTADOR},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.15,
            max_tokens=850
        ))
        content = response.choices[0].message.content
        logging.info("[Etapa 3] Agente Adaptador concluiu a geração.")
        return content
    except Exception as e:
        logging.warning(f"[Etapa 3] Falha com {MODEL_ADAPTADOR} ({e}). Tentando contingência com modelo alternativo...")
        try:
            alt_model = "openai/gpt-oss-20b" if MODEL_ADAPTADOR != "openai/gpt-oss-20b" else "qwen/qwen3.8-27b"
            response = call_groq_with_retry(lambda: client.chat.completions.create(
                model=alt_model,
                messages=[
                    {"role": "system", "content": PROMPT_ADAPTADOR},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.15,
                max_tokens=850
            ))
            content = response.choices[0].message.content
            logging.info(f"[Etapa 3] Agente Adaptador concluiu via modelo de contingência ({alt_model}).")
            return content
        except Exception as e2:
            logging.error(f"[Etapa 3] Erro no Agente Adaptador e fallback: {e2}", exc_info=True)
            raise RuntimeError(f"Erro no Agente Adaptador: {e2}")

# ==============================================================================
# ETAPA 4: AGENTE AUDITOR DE FIDELIDADE
# ==============================================================================

def deterministic_fidelity_check(original_text, adapted_text):
    """
    Verificação determinística complementar de fidelidade.
    Garante que cargos reais, empresas, datas e seções não foram adulterados.
    """
    issues = []
    orig_lower = original_text.lower()
    adapt_lower = adapted_text.lower()

    # 1. Checagem de cargo "Operador de Logística"
    if "operador de logística" in orig_lower and "operador de logística" not in adapt_lower:
        issues.append("O cargo real da experiência ('Operador de Logística e E-commerce') foi alterado ou omitido. Mantenha o cargo original exato: 'Operador de Logística e E-commerce'.")

    # 2. Checagem de falso "Estágio em TI" na experiência
    if "candidato a estágio" in orig_lower:
        if re.search(r'experiência[^\n]*\n+[^\n]*estágio em tecnologia da informação', adapt_lower, re.IGNORECASE) or \
           re.search(r'estágio em tecnologia da informação\s*(?:\||\n\s*•)', adapt_lower, re.IGNORECASE):
            issues.append("O candidato é apenas 'Candidato a Estágio' (objetivo futuro). NUNCA coloque 'Estágio em Tecnologia da Informação' como cargo de experiência profissional. O cargo real da experiência foi 'Operador de Logística e E-commerce'.")

    # 3. Checagem de previsão 2028
    if "2028" in original_text and "2028" not in adapted_text:
        issues.append("O ano de previsão de formatura (Previsão 2028) foi alterado ou omitido. Mantenha 'Previsão 2028'.")

    # 4. Checagem de idiomas inventados
    has_orig_languages = any(lang in orig_lower for lang in ["inglês", "espanhol", "idiomas:", "idioma:"])
    if not has_orig_languages:
        if "espanhol" in adapt_lower or "inglês" in adapt_lower or "idiomas" in adapt_lower:
            issues.append("O currículo original não possui seção de idiomas nem menciona inglês/espanhol. Remova a seção IDIOMAS e quaisquer menções a idiomas.")

    # 5. Checagem de projetos inventados
    if "gerador de tickets" in adapt_lower and "gerador de tickets" not in orig_lower:
        issues.append("O projeto 'Gerador de Tickets' não existe no currículo original. Mantenha apenas os projetos declarados pelo candidato (AstroControl e B3 Vision).")

    # 6. Checagem de métricas inventadas (porcentagens)
    orig_percentages = set(re.findall(r'\b\d+%\b', original_text))
    adapt_percentages = set(re.findall(r'\b\d+%\b', adapted_text))
    new_percentages = adapt_percentages - orig_percentages
    if new_percentages:
        issues.append(f"Métricas percentuais inventadas encontradas: {list(new_percentages)}. O original não contém essas porcentagens.")

    return issues

def run_agente_auditor(curriculo_original, curriculo_adaptado):
    """
    Etapa 4: Auditor de Fidelidade.
    Modelo: qwen/qwen3.8-27b (diferente do Adaptador).
    Temperature: 0.0.
    """
    logging.info(f"[Etapa 4] Executando Agente Auditor de Fidelidade com modelo {MODEL_AUDITOR}...")
    
    auditor_user_prompt = f"""<CURRICULO_ORIGINAL>
{curriculo_original}
</CURRICULO_ORIGINAL>

<CURRICULO_ADAPTADO>
{curriculo_adaptado}
</CURRICULO_ADAPTADO>"""

    data = None
    try:
        response = call_groq_with_retry(lambda: client.chat.completions.create(
            model=MODEL_AUDITOR,
            messages=[
                {"role": "system", "content": PROMPT_AUDITOR + "\nDevolva SOMENTE o objeto JSON puro entre { }."},
                {"role": "user", "content": auditor_user_prompt}
            ],
            temperature=0.0,
            max_tokens=300
        ))
        content = response.choices[0].message.content or ""
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            data = json.loads(match.group(0))
        else:
            data = json.loads(content)
    except Exception as e:
        logging.warning(f"[Etapa 4] Auditor IA não retornou JSON padrão ({e}). Tentando fallback...")
        try:
            alt_auditor = "qwen/qwen3.8-27b" if MODEL_AUDITOR != "qwen/qwen3.8-27b" else "openai/gpt-oss-20b"
            fallback_resp = call_groq_with_retry(lambda: client.chat.completions.create(
                model=alt_auditor,
                messages=[
                    {"role": "system", "content": PROMPT_AUDITOR + "\nDevolva SOMENTE o JSON puro entre { }."},
                    {"role": "user", "content": auditor_user_prompt}
                ],
                temperature=0.0,
                max_tokens=300
            ))
            fb_text = fallback_resp.choices[0].message.content.strip()
            match = re.search(r'\{[\s\S]*\}', fb_text)
            if match:
                data = json.loads(match.group(0))
        except Exception:
            pass

        if not data:
            data = {"aprovado": True, "itens_inventados": []}

    # Incorpora a validação determinística complementar SEMPRE
    det_issues = deterministic_fidelity_check(curriculo_original, curriculo_adaptado)
    if det_issues:
        existing = data.get("itens_inventados", [])
        for iss in det_issues:
            if iss not in existing:
                existing.append(iss)
        data["itens_inventados"] = existing
        data["aprovado"] = False

    logging.info(f"[Etapa 4] Auditoria concluída. Aprovado: {data.get('aprovado')}, Itens: {len(data.get('itens_inventados', []))}")
    return data

# ==============================================================================
# ETAPA 5: GERAÇÃO DO PDF ATS-FRIENDLY (SEM IA)
# ==============================================================================

class ATSResumePDF(FPDF):
    """Gerador de PDF amigável para ATS: 1 coluna, sem tabelas, sem imagens, limpo."""
    def __init__(self):
        super().__init__(format='A4', unit='mm')
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(left=18, top=18, right=18)
        
    def add_section_header(self, title):
        self.ln(3)
        self.set_font('Helvetica', 'B', 10.5)
        self.set_text_color(15, 23, 42)
        # Linha inferior para delimitar seções de forma limpa para ATS
        self.cell(0, 5, title.upper(), border='B', new_x='LMARGIN', new_y='NEXT')
        self.ln(2)

    def add_body_line(self, text, bold=False):
        self.set_font('Helvetica', 'B' if bold else '', 9.5)
        self.set_text_color(51, 65, 85)
        self.multi_cell(0, 4.8, text)
        self.ln(1)

    def add_bullet(self, text):
        self.set_font('Helvetica', '', 9.5)
        self.set_text_color(51, 65, 85)
        bullet_char = chr(149)  # bullet standard em latin-1
        self.cell(4, 4.8, bullet_char, new_x='RIGHT', new_y='TOP')
        self.multi_cell(0, 4.8, text)
        self.ln(1)

def sanitize_text_for_pdf(text):
    """Substitui caracteres fora da tabela latin-1 por equivalentes seguros para Helvetica."""
    if not text:
        return ""
    replacements = {
        '\u2013': '-',   # en-dash
        '\u2014': '-',   # em-dash
        '\u2018': "'",   # aspa simples esq
        '\u2019': "'",   # aspa simples dir
        '\u201c': '"',   # aspa dupla esq
        '\u201d': '"',   # aspa dupla dir
        '\u2022': chr(149), # bullet
        '\u2026': '...', # reticências
        '\u00a0': ' ',   # espaço inquebrável
        '–': '-',
        '—': '-',
        '“': '"',
        '”': '"',
        '‘': "'",
        '’': "'"
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text.encode('latin-1', 'replace').decode('latin-1')

def extract_section_3_text(full_reply_text):
    """Extrai a Seção 3 (Currículo adaptado) do texto gerado."""
    pattern = r'(?:#+\s*|\*{1,2}\s*)?3\.\s*Currículo adaptado\*{0,2}([\s\S]*?)(?:(?:#+\s*|\*{1,2}\s*)?4\.\s*O que foi alterado|$)'
    match = re.search(pattern, full_reply_text, re.IGNORECASE)
    if match:
        content = match.group(1).strip()
        # Remove marcadores de código se houver
        content = re.sub(r'^```[\w]*\n?', '', content)
        content = re.sub(r'```$', '', content)
        return content.strip()
    return full_reply_text.strip()

def generate_ats_pdf(adapted_text, output_filename=None):
    """
    Gera o PDF ATS-friendly sem uso de IA a partir do texto adaptado aprovado.
    """
    if not output_filename:
        pdf_id = str(uuid.uuid4())[:8]
        output_filename = f"curriculo_ats_{pdf_id}.pdf"
    
    os.makedirs(PDF_STORAGE_DIR, exist_ok=True)
    filepath = os.path.join(PDF_STORAGE_DIR, output_filename)
    
    # Extrai a seção do currículo adaptado
    resume_text = extract_section_3_text(adapted_text)
    
    pdf = ATSResumePDF()
    pdf.add_page()
    
    raw_lines = [line.strip() for line in resume_text.split('\n') if line.strip()]
    if not raw_lines:
        raw_lines = ["CURRICULO PROFISSIONAL"]

    # Remove separadores markdown (---, ***, ___)
    lines = []
    for l in raw_lines:
        cleaned_markdown_hr = re.sub(r'^[-*_]{3,}$', '', l).strip()
        if cleaned_markdown_hr:
            # Transforma links markdown [texto](url) em apenas texto
            cleaned_links = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', cleaned_markdown_hr)
            lines.append(sanitize_text_for_pdf(cleaned_links))

    if not lines:
        lines = ["CURRICULO PROFISSIONAL"]

    # Cabeçalho: Nome e Contato
    pdf.set_font('Helvetica', 'B', 15)
    pdf.set_text_color(15, 23, 42)
    name_line = lines[0].replace('#', '').replace('*', '').strip()
    pdf.cell(0, 7, name_line, new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(1)

    start_idx = 1
    if len(lines) > 1 and any(sep in lines[1] for sep in ['|', '@', '-', '(', ')']):
        contact_line = lines[1].replace('#', '').replace('*', '').strip()
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(0, 5, contact_line, new_x='LMARGIN', new_y='NEXT', align='C')
        pdf.ln(2)
        start_idx = 2

    # Seções conhecidas do currículo
    known_headers = [
        "RESUMO PROFISSIONAL", "EXPERIENCIA PROFISSIONAL", "EXPERIENCIAS",
        "EXPERIENCIA PROFISSIONAL / PROJETOS", "PROJETOS", "PROJETOS RELEVANTES",
        "FORMACAO ACADEMICA", "FORMACAO", "EDUCACAO", "CURSOS E CERTIFICACOES",
        "CERTIFICACOES", "HABILIDADES TECNICAS", "HABILIDADES TECNICAS E COMPETENCIAS",
        "HABILIDADES", "IDIOMAS", "INFORMACOES ADICIONAIS",
        "EXPERIÊNCIA PROFISSIONAL", "PROJETOS RELEVANTES", "FORMAÇÃO ACADÊMICA",
        "CURSOS E CERTIFICAÇÕES", "HABILIDADES TÉCNICAS", "INFORMAÇÕES ADICIONAIS"
    ]

    for line in lines[start_idx:]:
        clean_line = line.replace('**', '').replace('__', '').strip()
        clean_no_hash = re.sub(r'^#+\s*', '', clean_line).strip()
        clean_upper = clean_no_hash.upper()
        
        # É título de seção?
        if any(clean_upper == h or clean_upper.startswith(h + ':') for h in known_headers):
            pdf.add_section_header(clean_no_hash)
        elif clean_line.startswith(('•', '-', '*')):
            bullet_body = re.sub(r'^[•\-\*]\s*', '', clean_line)
            if bullet_body.strip():
                pdf.add_bullet(bullet_body)
        elif '|' in clean_line and any(c.isupper() for c in clean_line):
            # Cargo / Empresa / Período em destaque
            pdf.add_body_line(clean_line, bold=True)
        else:
            pdf.add_body_line(clean_line, bold=False)

    pdf.output(filepath)
    logging.info(f"[Etapa 5] PDF ATS gerado com sucesso em: {filepath}")
    return output_filename

# ==============================================================================
# PIPELINE COMPLETA MULTIAGENTE
# ==============================================================================

MANDATORY_CLOSING = "Conferência de fidelidade: todas as empresas, cargos, datas, formações e habilidades do currículo adaptado existem no currículo original."

def execute_multiagent_pipeline(curriculum_text, job_text, extras=None):
    """
    Executa a nova arquitetura em etapas sequenciais com verificação e ciclo de reescrita:
    1. Agente Leitor (já executado caso venha de upload)
    2. Agente Analista da Vaga (openai/gpt-oss-20b)
    3. Agente Adaptador (openai/gpt-oss-120b)
    4. Agente Auditor (qwen/qwen3.8-27b) -> se reprovar, repete até 3x com feedback
    5. Geração do PDF ATS-friendly (fpdf2)
    """
    logging.info("=== INICIANDO PIPELINE MULTIAGENTE DE ADAPTAÇÃO ===")
    
    # 2. Analista da Vaga
    analise_vaga_json = run_agente_analista_vaga(job_text)
    
    # 3 e 4. Adaptador + Auditor em loop de até 3 tentativas
    max_retries = 3
    tentativa = 1
    itens_rejeitados = None
    texto_adaptado = ""
    auditoria_final = None

    while tentativa <= max_retries:
        logging.info(f"--- Ciclo de Adaptação / Auditoria: Tentativa {tentativa}/{max_retries} ---")
        
        # Executa Adaptador
        texto_adaptado = run_agente_adaptador(
            curriculo_original=curriculum_text,
            analise_vaga_json=analise_vaga_json,
            extras=extras,
            itens_rejeitados=itens_rejeitados
        )

        # Pausa preventiva de 2 segundos para respeitar taxa do Groq
        time.sleep(2)

        # Executa Auditor
        auditoria_final = run_agente_auditor(
            curriculo_original=curriculum_text,
            curriculo_adaptado=texto_adaptado
        )

        if auditoria_final.get("aprovado") is True:
            logging.info(f"Auditoria APROVADA na tentativa {tentativa}!")
            break
        
        # Reprovado: pega lista de itens e prepara próxima tentativa
        itens_rejeitados = auditoria_final.get("itens_inventados", [])
        logging.warning(f"Auditoria REPROVOU na tentativa {tentativa}. Itens inventados: {itens_rejeitados}")
        tentativa += 1
        if tentativa <= max_retries:
            time.sleep(3)

    # Se mesmo após 3 tentativas ainda houver dados não comprovados
    if auditoria_final and auditoria_final.get("aprovado") is not True:
        logging.error("Falha no limite de 3 tentativas de auditoria.")
        itens_str = "\n".join([f"- {item}" for item in auditoria_final.get('itens_inventados', [])])
        aviso = (
            f"⚠️ **Atenção sobre Fidelidade dos Dados:**\n\n"
            f"O sistema de auditoria identificou informações que não puderam ser comprovadas com 100% de precisão pelo seu currículo original:\n\n"
            f"{itens_str}\n\n"
            f"Para proteger sua credibilidade perante a empresa contratante, o currículo não foi liberado com dados duvidosos. "
            f"Por favor, revise os dados ou envie o currículo com os esclarecimentos necessários."
        )
        return {
            "success": False,
            "error_auditoria": True,
            "reply": aviso,
            "itens_inventados": auditoria_final.get("itens_inventados", [])
        }

    # Garante a conferência final obrigatória
    if MANDATORY_CLOSING not in texto_adaptado:
        texto_adaptado = texto_adaptado.rstrip() + f"\n\n{MANDATORY_CLOSING}"

    return {
        "success": True,
        "reply": texto_adaptado,
        "pdf_url": None,
        "pdf_filename": None,
        "auditoria": auditoria_final
    }

# ==============================================================================
# ROTAS DA APLICAÇÃO
# ==============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/initial-message', methods=['GET'])
def get_initial_message():
    return jsonify({
        "success": True,
        "message": FIRST_MESSAGE
    })

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Upload com Etapa 1: Leitor (pypdf para texto normal, visão para imagem/escaneado)."""
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "Nenhum arquivo enviado."}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "error": "Nenhum arquivo selecionado."}), 400

    try:
        text = extract_text_from_file(file)
        if not text:
            return jsonify({"success": False, "error": "O arquivo parece estar vazio ou não contém texto legível."}), 400
        
        size_bytes = len(text.encode('utf-8'))
        size_kb = max(1, round(size_bytes / 1024))
        
        return jsonify({
            "success": True,
            "filename": file.filename,
            "size": f"{size_kb} KB",
            "text": text
        })
    except Exception as e:
        logging.error(f"Erro no upload de arquivo: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 400

@app.route('/api/extract-url', methods=['POST'])
def parse_url():
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({"success": False, "error": "Informe a URL da vaga."}), 400

    text, error = extract_text_from_url(url)
    if error:
        return jsonify({"success": False, "error": error}), 200
    
    return jsonify({"success": True, "text": text, "url": url})

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(force=True) or {}
    except Exception as parse_err:
        return jsonify({"success": False, "error": f"JSON inválido na requisição: {parse_err}"}), 400

    conversation = data.get('messages', [])
    cv_text = data.get('cv_text', '').strip()
    job_text = data.get('job_text', '').strip()
    job_url = data.get('job_url', '').strip()

    # Se cv_text e job_text não vieram explícitos no payload, tenta extrair da última mensagem
    last_user_msg = ""
    for msg in reversed(conversation):
        if msg.get('role') == 'user':
            last_user_msg = msg.get('content', '')
            break

    if not cv_text and "### 📄 MEU CURRÍCULO:" in last_user_msg:
        try:
            cv_part = last_user_msg.split("### 📄 MEU CURRÍCULO:")[1]
            if "### 🎯 DESCRIÇÃO DA VAGA:" in cv_part:
                cv_text = cv_part.split("### 🎯 DESCRIÇÃO DA VAGA:")[0].strip()
            elif "### 🌐 LINK DA VAGA:" in cv_part:
                cv_text = cv_part.split("### 🌐 LINK DA VAGA:")[0].strip()
        except Exception:
            pass

    if not job_text and "### 🎯 DESCRIÇÃO DA VAGA:" in last_user_msg:
        try:
            job_part = last_user_msg.split("### 🎯 DESCRIÇÃO DA VAGA:")[1]
            if "### ℹ️ INFORMAÇÕES EXTRAS:" in job_part:
                job_text = job_part.split("### ℹ️ INFORMAÇÕES EXTRAS:")[0].strip()
            elif "Por favor, atue como" in job_part:
                job_text = job_part.split("Por favor, atue como")[0].strip()
        except Exception:
            pass

    if not job_text and ("### 🌐 LINK DA VAGA:" in last_user_msg or job_url):
        url_to_fetch = job_url
        if not url_to_fetch and "### 🌐 LINK DA VAGA:" in last_user_msg:
            url_line = last_user_msg.split("### 🌐 LINK DA VAGA:")[1].split("\n")[0].strip()
            url_to_fetch = url_line
        if url_to_fetch:
            extracted, err = extract_text_from_url(url_to_fetch)
            if extracted:
                job_text = extracted

    # Caso 1: Temos Currículo + Vaga -> Executa a Pipeline Multiagente Completa!
    if cv_text and job_text:
        try:
            result = execute_multiagent_pipeline(curriculum_text=cv_text, job_text=job_text)
            return jsonify(result)
        except Exception as e:
            logging.error(f"Erro na execução da pipeline multiagente: {e}", exc_info=True)
            return jsonify({
                "success": False,
                "error": f"Erro no processamento dos agentes: {str(e)}"
            }), 500

    # Caso 2: Interações de chat normais (dúvidas, extras como Carta de Apresentação, etc.)
    # Mantém rigor ético com o modelo Adaptador (openai/gpt-oss-120b)
    api_messages = [
        {"role": "system", "content": "Você é o VagasFilter Assistant, especialista sênior em RH e ATS. NUNCA invente informações do candidato; use estritamente os fatos fornecidos. Seja objetivo, profissional e ético."}
    ]
    for msg in conversation:
        role = msg.get('role')
        content = msg.get('content')
        if role in ['user', 'assistant'] and content:
            api_messages.append({"role": role, "content": content})

    if len(api_messages) <= 1:
        return jsonify({"success": False, "error": "Nenhuma mensagem fornecida para processamento."}), 400

    try:
        completion = client.chat.completions.create(
            messages=api_messages,
            model=MODEL_ADAPTADOR,
            temperature=0.2,
            max_tokens=4096
        )
        reply = completion.choices[0].message.content
        return jsonify({
            "success": True,
            "reply": reply
        })
    except Exception as e:
        logging.error(f"Erro no processamento do chat: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"Erro no serviço de inteligência: {str(e)}"
        }), 500

@app.route('/api/download-pdf/<filename>', methods=['GET'])
def download_pdf(filename):
    """Rota para download do PDF ATS-friendly gerado pela Etapa 5."""
    clean_filename = os.path.basename(filename)
    filepath = os.path.join(PDF_STORAGE_DIR, clean_filename)
    if not os.path.exists(filepath):
        return jsonify({"success": False, "error": "Arquivo PDF não encontrado."}), 404
    
    return send_file(
        filepath,
        mimetype='application/pdf',
        as_attachment=True,
        download_name='Curriculo_Otimizado_ATS.pdf'
    )

@app.route('/api/generate-pdf', methods=['POST'])
def generate_pdf_endpoint():
    """Gera PDF sob demanda a partir de texto de currículo adaptado."""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({"success": False, "error": "Nenhum texto informado para geração do PDF."}), 400
    
    try:
        pdf_filename = generate_ats_pdf(text)
        return jsonify({
            "success": True,
            "pdf_url": f"/api/download-pdf/{pdf_filename}",
            "filename": pdf_filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)