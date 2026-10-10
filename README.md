# VagasFilter 📄🤖

> Agente de IA que ajuda a criar e melhorar currículos, do rascunho ao documento pronto em minutos.

**Aluno:** Lucas Sales
**Aplicação online:** [link do deploy no Render]

---

## 🎯 Objetivo

Muita gente não sabe montar um currículo claro e profissional, ou não consegue adaptá-lo para cada vaga. Este agente resolve esse problema: o usuário informa seus dados (ou cola um currículo existente) e recebe um texto organizado, com linguagem profissional e foco na vaga desejada.

**Público-alvo:** estudantes, jovens em busca do primeiro emprego e pessoas em transição de carreira.

---

## 🛠️ Stack Tecnológica

| Tecnologia | Para que serve |
|---|---|
| **Python** | Linguagem principal do projeto |
| **Streamlit** | Interface web onde o usuário conversa com o agente |
| **Groq API** | Acesso rápido ao modelo de IA |
| **GitHub** | Armazenamento e versionamento do código |
| **Render** | Publicação da aplicação online |
| **Neon** | Banco de dados PostgreSQL *(remova se não foi usado)* |

---

## ⚙️ Como Funciona

```
USUÁRIO
   ↓
STREAMLIT          → recebe a entrada e exibe a resposta
   ↓
AGENTE / PROMPT    → define o comportamento e as regras do agente
   ↓
GROQ API           → envia o pedido ao modelo
   ↓
MODELO DE IA       → interpreta e gera o texto
   ↓
RESPOSTA           → o currículo volta para a tela do usuário
```

---

## 📁 Estrutura do Projeto

```
[nome-do-repositorio]/
├── app.py              # Aplicação Streamlit (interface + chamada à API)
├── prompt.md           # Prompt que deu origem ao agente
├── requirements.txt    # Dependências do projeto
├── .env.example        # Exemplo das variáveis de ambiente
└── README.md           # Este arquivo
```

> Ajuste a estrutura acima para refletir os arquivos reais do seu repositório.

---

## 🚀 Como Executar Localmente

**1. Clone o repositório**
```bash
git clone https://github.com/[seu-usuario]/[nome-do-repositorio].git
cd [nome-do-repositorio]
```

**2. Crie e ative um ambiente virtual**
```bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows
```

**3. Instale as dependências**
```bash
pip install -r requirements.txt
```

**4. Configure as variáveis de ambiente**

Crie um arquivo `.env` na raiz do projeto:
```
GROQ_API_KEY=sua_chave_aqui
```
> Obtenha sua chave gratuita em [console.groq.com](https://console.groq.com).
> Nunca envie o arquivo `.env` para o GitHub.

**5. Rode a aplicação**
```bash
streamlit run app.py
```

---

## ☁️ Deploy

A aplicação está publicada no **Render**. Para publicar a sua:

1. Conecte o repositório do GitHub ao Render
2. Defina o comando de build: `pip install -r requirements.txt`
3. Defina o comando de start: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
4. Adicione a variável de ambiente `GROQ_API_KEY` no painel do Render

---

## 🧠 O Prompt do Agente

O comportamento do agente é definido no arquivo [`prompt.md`](prompt.md), que contém o prompt usado para criá-lo: papel, tom de voz, regras e formato das respostas.


---

## 👤 Autor

**[seu nome]** · Turma [sua turma]
[LinkedIn ou GitHub]
