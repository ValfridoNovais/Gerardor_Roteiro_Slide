# app.py
import streamlit as st
import fitz                     # PyMuPDF
from fpdf import FPDF
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import os
import json
import re
from datetime import datetime
from typing import List, Dict

# --------------------------------------------------
# CONFIGURAÇÃO GERAL
# --------------------------------------------------
# Carrega variáveis de ambiente (como a chave da API da OpenAI) de um arquivo .env
load_dotenv()

# Instancia o cliente da OpenAI. Ele buscará a chave OPENAI_API_KEY automaticamente.
try:
    client = OpenAI()
except Exception as e:
    st.error(f"Erro ao inicializar o cliente da OpenAI. Verifique sua chave de API. Erro: {e}")
    st.stop()


# Define os diretórios base do projeto
ROOT = Path(__file__).parent
JSON_DIR = ROOT / "roteiros_gerados"
JSON_DIR.mkdir(exist_ok=True)

# Configura a página do Streamlit
st.set_page_config(page_title="Gerador de Roteiros – Análise Criminal",
                   layout="wide")

# --------------------------------------------------
# FUNÇÕES AUXILIARES
# --------------------------------------------------

def extrair_texto_pdf(uploaded_file, start: int, end: int) -> List[str]:
    """Extrai o texto de um intervalo de páginas de um arquivo PDF."""
    stream_data = uploaded_file.read()
    doc = fitz.open(stream=stream_data, filetype="pdf")
    uploaded_file.seek(0) # Reseta o ponteiro do arquivo para reutilização
    return [doc[i].get_text("text", sort=True) for i in range(start - 1, end)]

def planejar_tempos_dos_slides(conteudos_slides: List[str], tempo_total_minutos: int, pag_ini: int):
    """(Etapa 1) Pede à IA para analisar todos os slides e alocar o tempo total entre eles."""
    slides_formatados = "\n".join([f"Slide {pag_ini + i}: {conteudo.strip()}" for i, conteudo in enumerate(conteudos_slides)])
    tempo_total_segundos = tempo_total_minutos * 60

    prompt_planejador = f"""
        Você é um especialista em design instrucional e roteirista de apresentações de Análise Criminal.
        Sua tarefa é planejar a distribuição de tempo para uma apresentação.

        A apresentação tem um tempo total de {tempo_total_minutos} minutos ({tempo_total_segundos} segundos).

        Aqui está o conteúdo dos slides que serão apresentados:
        ---
        {slides_formatados}
        ---

        Analise a importância e densidade de cada slide. Distribua o tempo total ({tempo_total_segundos} segundos) entre eles.
        Slides densos ou cruciais devem receber mais tempo; slides de transição ou simples, menos tempo.

        Sua resposta DEVE ser um objeto JSON válido. O objeto deve ter uma chave "plano", que contém uma lista.
        Cada item na lista representa um slide e deve ter:
        - "slide_num": (int) O número do slide (deve corresponder aos números fornecidos acima).
        - "tempo_atribuido_segundos": (int) O tempo em SEGUNDOS alocado para este slide.

        A soma de todos os "tempo_atribuido_segundos" deve ser igual a {tempo_total_segundos}.
        """
    try:
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_planejador}],
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        plano_json = json.loads(resposta.choices[0].message.content)
        return plano_json.get('plano', [])
    except Exception as e:
        st.error(f"Erro ao planejar os tempos (API ou JSON): {e}")
        return None

def gerar_roteiro_para_um_slide(slide_num, conteudo_slide, tempo_segundos, tipo, roteiro_anterior=""):
    """(Etapa 2) Gera o roteiro para um único slide com base no tempo alocado."""
    if tempo_segundos >= 60:
        tempo_desc = f"{tempo_segundos // 60} minuto(s) e {tempo_segundos % 60} segundos"
    else:
        tempo_desc = f"{tempo_segundos} segundos"

    prompt = f"""
        Você é um professor universitário de Análise Criminal.

        Gere um roteiro falado para o Slide {slide_num} de uma aula que já está em andamento.
        O roteiro deve fluir naturalmente a partir do roteiro anterior.

        Conteúdo do Slide Atual (Slide {slide_num}):
        "{conteudo_slide.strip()}"

        **O tempo de fala para ESTE slide específico deve ser de aproximadamente {tempo_desc}.**

        Tipo do slide: {tipo}.

        Roteiro do Slide Anterior (para dar continuidade):
        "{roteiro_anterior.strip()}"

        Com base nisso, gere um roteiro falado didático e técnico.
        Seja conciso e objetivo para respeitar o tempo alocado.
        Utilize exemplos reais e legislação brasileira quando aplicável e pertinente ao tópico.
        """
    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return resposta.choices[0].message.content.strip()

class PDF(FPDF):
    """Classe PDF corrigida para usar exclusivamente a fonte Arial do Windows."""
    def __init__(self):
        super().__init__()
        font_dir = "C:/Windows/Fonts/"
        font_styles = {
            '': 'arial.ttf',      # Regular
            'B': 'arialbd.ttf',   # Negrito
            'I': 'ariali.ttf',    # Itálico
            'BI': 'arialbi.ttf'   # Negrito e Itálico
        }
        fonte_regular_encontrada = False
        for style, font_file in font_styles.items():
            font_path = Path(font_dir) / font_file
            if font_path.exists():
                self.add_font("Arial", style, font_path, uni=True)
                if style == '':
                    fonte_regular_encontrada = True
            else:
                print(f"Aviso: Arquivo de fonte não encontrado: {font_path}")

        if not fonte_regular_encontrada:
            mensagem_erro = "A fonte principal 'arial.ttf' não foi encontrada em 'C:/Windows/Fonts/'. O app não funcionará sem as fontes padrão do Windows."
            st.error(mensagem_erro)
            raise FileNotFoundError(mensagem_erro)

    def header(self):
        self.set_font("Arial", "", 12)
        self.cell(0, 10, "Roteiros de Aula – Análise Criminal", ln=True, align="C")

def exportar_pdf(roteiros: dict) -> bytes:
    """Exporta os roteiros para um arquivo PDF em memória, usando a fonte Arial."""
    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for num, texto in roteiros.items():
        pdf.add_page()
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, f"Slide {num}", ln=True)
        pdf.set_font("Arial", "", 12)
        pdf.multi_cell(0, 10, texto)
    return bytes(pdf.output(dest='S'))

def salvar_json(meta: dict, roteiros: dict, textos: List[str], pag_ini: int) -> Path:
    """Salva os metadados e os roteiros gerados em um arquivo JSON."""
    data = {"criado_em": datetime.now().isoformat(), **meta, "slides": {}}
    for n, rote in roteiros.items():
        indice_texto = n - pag_ini
        if 0 <= indice_texto < len(textos):
            tema = textos[indice_texto].split("\n")[0]
        else:
            tema = "Tema não encontrado"
        data["slides"][f"Slide {n}"] = {"tema": tema.strip(), "roteiro": rote}
    nome = JSON_DIR / f"roteiro_{datetime.now():%Y%m%d_%H%M%S}.json"
    with open(nome, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    return nome

def listar_jsons():
    """Retorna lista de arquivos JSON de roteiro, ordenados por data."""
    return sorted(JSON_DIR.glob("roteiro_*.json"), reverse=True)

def filtrar_por_data(jsons, ano, mes, dia):
    """Filtra uma lista de arquivos JSON com base em ano, mês ou dia."""
    pattern = f"{ano}{mes:02d}{dia:02d}" if dia else f"{ano}{mes:02d}" if mes else f"{ano}"
    return [p for p in jsons if re.search(rf"roteiro_{pattern}", p.name)]

# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------
st.sidebar.title("Controles")

pdf_up = st.sidebar.file_uploader("📤 PDF dos slides", type="pdf")
pag_ini = st.sidebar.number_input("Página inicial", 1, 9999, 1, help="A primeira página do seu PDF que será usada.")
pag_fim = st.sidebar.number_input("Página final", pag_ini, 9999, pag_ini, help="A última página do seu PDF que será usada.")
tempo_total = st.sidebar.number_input("Tempo total (min)", 1, 10_000, 30, help="Duração total da apresentação para o intervalo de páginas selecionado.")

gerar_btn = st.sidebar.button("🚀 Gerar Roteiros")
st.sidebar.divider()

if 'roteiros_atuais' in st.session_state and st.session_state.roteiros_atuais:
    st.sidebar.subheader("Download do Roteiro Atual")
    pdf_bytes = exportar_pdf(st.session_state.roteiros_atuais)
    st.sidebar.download_button(
        label="📥 Baixar Roteiro em PDF",
        data=pdf_bytes,
        file_name="roteiro_aula_analise_criminal.pdf",
        mime="application/pdf"
    )
    st.sidebar.divider()

st.sidebar.subheader("Abrir roteiro salvo")
try:
    anos_disp = sorted({p.name[8:12] for p in listar_jsons()}, reverse=True)
except Exception:
    anos_disp = []
ano_sel = st.sidebar.selectbox("Ano", [""] + anos_disp)
mes_sel = st.sidebar.selectbox("Mês", [""] + list(range(1, 13)))
dia_sel = st.sidebar.selectbox("Dia", [""] + list(range(1, 32)))
jsons_filtrados = listar_jsons()
if ano_sel:
    jsons_filtrados = filtrar_por_data(jsons_filtrados, ano_sel, int(mes_sel) if mes_sel else 0, int(dia_sel) if dia_sel else 0)
json_nome = st.sidebar.selectbox("Arquivos", [""] + [p.name for p in jsons_filtrados])
carregar_btn = st.sidebar.button("📂 Carregar selecionado")

json_ext = st.sidebar.file_uploader("…ou subir JSON externo", type="json")
st.sidebar.divider()
if st.sidebar.button("🧹 Limpar Sessão"):
    st.session_state.clear()
    st.rerun()

# --------------------------------------------------
# FLUXO PRINCIPAL DA APLICAÇÃO (VERSÃO CORRIGIDA)
# --------------------------------------------------
st.title("👨‍🏫 Gerador de Roteiros para Aulas de Análise Criminal")

def exibir_dados_json(dados):
    # ... (esta função permanece a mesma, não precisa alterar)
    st.header(f"Roteiro carregado (Criado em: {dados.get('criado_em', 'Data desconhecida')})")
    roteiros_carregados = {}
    for slide, info in dados["slides"].items():
        try:
            num = int(re.search(r'\d+', slide).group())
        except (AttributeError, ValueError):
            num = slide
        roteiros_carregados[num] = info["roteiro"]
    st.session_state.roteiros_atuais = roteiros_carregados
    st.info("Roteiro carregado. Use o botão 'Baixar Roteiro em PDF' na barra lateral se desejar.")
    st.rerun()

# --- Bloco de Carregamento de JSON (permanece igual) ---
if carregar_btn and json_nome:
    try:
        with open(JSON_DIR / json_nome, "r", encoding="utf-8") as f:
            dados = json.load(f)
        exibir_dados_json(dados)
    except Exception as e:
        st.error(f"Erro ao carregar o arquivo JSON {json_nome}: {e}")
    st.stop()

if json_ext:
    try:
        dados = json.load(json_ext)
        exibir_dados_json(dados)
    except Exception as e:
        st.error(f"Erro ao carregar o arquivo JSON externo: {e}")
    st.stop()

# --- Bloco de Geração (com a primeira correção) ---
if gerar_btn and pdf_up:
    st.session_state.generator_used = True
    try:
        with fitz.open(stream=pdf_up.read(), filetype="pdf") as doc_tmp:
            total_pag_pdf = len(doc_tmp)
        pag_fim = min(pag_fim, total_pag_pdf)
        pdf_up.seek(0)
        textos = extrair_texto_pdf(pdf_up, pag_ini, pag_fim)
    except Exception as e:
        st.error(f"Erro ao ler o arquivo PDF: {e}")
        st.stop()

    with st.spinner("🧠 Etapa 1: Analisando slides e planejando a distribuição de tempo..."):
        plano_de_tempo = planejar_tempos_dos_slides(textos, tempo_total, pag_ini)

    if not plano_de_tempo:
        st.error("A IA não conseguiu gerar o plano de tempo. Tente novamente ou ajuste os parâmetros.")
        st.stop()

    st.success("Plano de tempo gerado!")
    with st.expander("⏱️ Ver Plano de Tempo Alocado pela IA"):
        st.json(plano_de_tempo)

    roteiros, anterior = {}, ""
    barra = st.progress(0., text="Preparando para gerar roteiros...")
    total_slides = len(textos)

    for idx, txt in enumerate(textos):
        num_slide = pag_ini + idx
        tipo = "inicial" if idx == 0 else "final" if idx == total_slides - 1 else "intermediário"
        tempo_alocado_segundos = next((item['tempo_atribuido_segundos'] for item in plano_de_tempo if item.get("slide_num") == num_slide), 30)
        barra.progress((idx) / total_slides, text=f"✍️ Etapa 2: Gerando roteiro para Slide {num_slide}/{pag_fim} ({tempo_alocado_segundos}s)...")
        
        roteiro_gerado = gerar_roteiro_para_um_slide(num_slide, txt, tempo_alocado_segundos, tipo, anterior)
        roteiros[num_slide] = roteiro_gerado
        anterior = roteiro_gerado
    
    barra.progress(1.0, text="✅ Geração Concluída!")
    st.session_state.roteiros_atuais = roteiros

    meta = {
        "nome_arquivo_origem": pdf_up.name,
        "total_paginas_pdf": total_pag_pdf,
        "pagina_inicio": pag_ini,
        "pagina_fim": pag_fim,
        "tempo_total_estimado_minutos": tempo_total
    }
    json_path = salvar_json(meta, roteiros, textos, pag_ini)
    st.sidebar.success(f"JSON salvo:\n{json_path.name}")
    st.success("Roteiro gerado! Você pode baixar o PDF na barra lateral.")
    st.rerun()

# --- NOVO BLOCO: Lógica para exibir o roteiro salvo na sessão ---
# Este bloco garante que o roteiro permaneça na tela após o st.rerun()
if 'roteiros_atuais' in st.session_state:
    st.subheader("Roteiro Gerado")
    # Itera sobre os roteiros salvos e os exibe
    for num, texto_roteiro in st.session_state.roteiros_atuais.items():
        # A correção do dólar é aplicada aqui também!
        texto_seguro = texto_roteiro.replace('$', r'\$')
        with st.expander(f"📚 Slide {num}", expanded=True):
            st.write(texto_seguro)

# --- Mensagem inicial (agora no final) ---
elif not any([st.session_state.get("generator_used"), json_ext, (carregar_btn and json_nome)]):
    st.info("Para começar, carregue um arquivo PDF na barra lateral, defina o intervalo de páginas, o tempo total da apresentação e clique em 'Gerar Roteiros'.")