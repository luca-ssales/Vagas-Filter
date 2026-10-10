/**
 * VagasFilter - Frontend Application Logic (Tema Claro & 3 Colunas)
 * Gestão de Stepper, Modal de Anexos, Chat Interativo e Exportação de Currículo
 */

document.addEventListener('DOMContentLoaded', () => {
  // Estado da Aplicação
  const state = {
    messages: [], // Array de {role: 'user'|'assistant', content: string}
    cvText: '',
    cvFileName: '',
    cvFileSize: '',
    jobText: '',
    jobUrl: '',
    jobTitle: '',
    isThinking: false,
    currentStep: 1, // 1: Aguardando CV, 2: Aguardando Vaga, 3: Processando, 4: Concluído
    lastPdfUrl: null
  };

  // Inicializador de Markdown
  const md = window.markdownit ? window.markdownit({
    html: false,
    linkify: true,
    typographer: true,
    breaks: true
  }) : {
    render: (src) => src.replace(/\n/g, '<br>')
  };

  // Elementos do DOM - Chat
  const chatMessagesEl = document.getElementById('chat-messages');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-user-input');
  const sendBtn = document.getElementById('btn-send-message');
  const resetBtn = document.getElementById('btn-reset-session');
  const btnOpenAttachment = document.getElementById('btn-open-attachment');

  // Elementos da Sidebar Direita - Stepper & Arquivos
  const step1 = document.getElementById('step-1');
  const step2 = document.getElementById('step-2');
  const step3 = document.getElementById('step-3');
  const step4 = document.getElementById('step-4');

  const badgeCvName = document.getElementById('badge-cv-name');
  const badgeCvMeta = document.getElementById('badge-cv-meta');
  const badgeJobName = document.getElementById('badge-job-name');
  const badgeJobMeta = document.getElementById('badge-job-meta');

  // Elementos do Modal de Anexos
  const modal = document.getElementById('attachment-modal');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnModalCancel = document.getElementById('btn-modal-cancel');
  const btnModalConfirm = document.getElementById('btn-modal-confirm');

  const modalCvDropzone = document.getElementById('modal-cv-dropzone');
  const modalCvFile = document.getElementById('modal-cv-file');
  const cvDropLabel = document.getElementById('cv-drop-label');
  const btnToggleModalCvText = document.getElementById('btn-toggle-modal-cv-text');
  const modalCvText = document.getElementById('modal-cv-text');

  const modalJobUrl = document.getElementById('modal-job-url');
  const btnModalFetchUrl = document.getElementById('btn-modal-fetch-url');
  const btnToggleModalJobText = document.getElementById('btn-toggle-modal-job-text');
  const modalJobText = document.getElementById('modal-job-text');
  const modalLinkedin = document.getElementById('modal-linkedin');
  const modalExperience = document.getElementById('modal-experience');

  const toastContainer = document.getElementById('toast-container');

  // Iniciar Aplicação
  initApp();

  async function initApp() {
    setupEventListeners();
    updateStepperUI();
    await loadInitialGreeting();
  }

  // Carregar Mensagem Inicial da IA
  async function loadInitialGreeting() {
    try {
      const res = await fetch('/api/initial-message');
      const data = await res.json();
      if (data && data.message) {
        addMessageToChat('assistant', data.message);
      }
    } catch (err) {
      const fallback = `Olá! 👋\nSou o VagasFilter Assistant, seu especialista em recrutamento e sistemas ATS.\nPara criar um currículo profundamente personalizado para a vaga que você quer, vou precisar de alguns dados:\n\n1. Seu currículo atual (em PDF ou TXT)\n2. A descrição da vaga (pode ser um texto ou um link)\n\nAssim que você enviar, eu faço a análise minuciosa, identifico as palavras-chave críticas e gero um currículo otimizado com padrão ouro para ATS.\n\nPode me enviar os arquivos ou colar as informações quando estiver pronto!`;
      addMessageToChat('assistant', fallback);
    }
  }

  function setupEventListeners() {
    // Chat Submit
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleUserSendMessage();
    });

    // Reset Session
    resetBtn.addEventListener('click', () => {
      if (confirm('Deseja iniciar um novo currículo e limpar os dados atuais?')) {
        resetSession();
      }
    });

    // Modal Triggers
    btnOpenAttachment.addEventListener('click', () => openModal());
    btnCloseModal.addEventListener('click', () => closeModal());
    btnModalCancel.addEventListener('click', () => closeModal());
    
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeModal();
    });

    // Modal Dropzone CV
    modalCvDropzone.addEventListener('click', () => modalCvFile.click());
    modalCvFile.addEventListener('change', (e) => {
      if (e.target.files.length) uploadFile(e.target.files[0], 'cv');
    });

    setupDragAndDrop(modalCvDropzone, (file) => uploadFile(file, 'cv'));

    // Toggle Textareas in Modal
    btnToggleModalCvText.addEventListener('click', () => {
      modalCvText.classList.toggle('hidden');
      if (!modalCvText.classList.contains('hidden')) modalCvText.focus();
    });

    modalCvText.addEventListener('input', () => {
      if (modalCvText.value.trim()) {
        state.cvText = modalCvText.value.trim();
        state.cvFileName = 'Currículo (Texto Colado)';
        state.cvFileSize = `${modalCvText.value.length} caracteres`;
        cvDropLabel.textContent = 'Texto colado com sucesso!';
        updateFilesSidebar();
      }
    });

    btnToggleModalJobText.addEventListener('click', () => {
      modalJobText.classList.toggle('hidden');
      if (!modalJobText.classList.contains('hidden')) modalJobText.focus();
    });

    modalJobText.addEventListener('input', () => {
      state.jobText = modalJobText.value.trim();
      state.jobTitle = 'Descrição da vaga (Texto)';
      updateFilesSidebar();
    });

    // Modal Fetch URL
    btnModalFetchUrl.addEventListener('click', handleFetchModalJobUrl);

    // Modal Confirm / Submit
    btnModalConfirm.addEventListener('click', handleModalConfirmSubmit);

    // Quick Chips Extras
    document.querySelectorAll('.chip-action').forEach(chip => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        if (state.isThinking) return;
        sendCustomUserPrompt(prompt);
      });
    });

    // Nav Links (demo interaction)
    document.getElementById('btn-nav-new').addEventListener('click', (e) => {
      e.preventDefault();
      openModal();
    });
  }

  function setupDragAndDrop(element, onDropCallback) {
    ['dragenter', 'dragover'].forEach(eventName => {
      element.addEventListener(eventName, (e) => {
        e.preventDefault();
        element.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      element.addEventListener(eventName, (e) => {
        e.preventDefault();
        element.classList.remove('dragover');
      });
    });

    element.addEventListener('drop', (e) => {
      if (e.dataTransfer.files.length) {
        onDropCallback(e.dataTransfer.files[0]);
      }
    });
  }

  // Upload CV via API
  async function uploadFile(file, type) {
    const formData = new FormData();
    formData.append('file', file);

    cvDropLabel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Lendo arquivo (OCR de visão se imagem)...';

    try {
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      });
      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Erro ao processar arquivo.');
      }

      state.cvText = data.text;
      state.cvFileName = data.filename;
      state.cvFileSize = data.size || 'PDF';
      cvDropLabel.innerHTML = `<i class="fa-solid fa-circle-check" style="color:var(--primary-green);"></i> <strong>${data.filename}</strong> (${data.size})`;
      
      updateFilesSidebar();
      showToast(`Arquivo "${data.filename}" carregado com sucesso!`, 'success');

      // Se ainda não estava no step 2, avança
      if (state.currentStep < 2) {
        state.currentStep = 2;
        updateStepperUI();
      }
    } catch (err) {
      cvDropLabel.textContent = 'Erro ao ler arquivo. Tente novamente ou cole o texto.';
      showToast(err.message, 'error');
    }
  }

  // Buscar URL da Vaga no Modal
  async function handleFetchModalJobUrl() {
    const url = modalJobUrl.value.trim();
    if (!url) {
      showToast('Por favor, informe o link da vaga.', 'error');
      modalJobUrl.focus();
      return;
    }

    btnModalFetchUrl.disabled = true;
    btnModalFetchUrl.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

    try {
      const response = await fetch('/api/extract-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const data = await response.json();

      if (!data.success || data.error) {
        showToast(data.error || 'Não foi possível ler o link. Cole o texto da vaga abaixo!', 'info');
        modalJobText.classList.remove('hidden');
        modalJobText.focus();
      } else if (data.text) {
        state.jobText = data.text;
        state.jobUrl = url;
        state.jobTitle = 'Descrição da vaga (Link)';
        modalJobText.value = data.text;
        showToast('Texto da vaga extraído com sucesso!', 'success');
        updateFilesSidebar();
      }
    } catch (err) {
      showToast('Erro ao acessar link. Cole a descrição da vaga diretamente.', 'info');
      modalJobText.classList.remove('hidden');
    } finally {
      btnModalFetchUrl.disabled = false;
      btnModalFetchUrl.textContent = 'Buscar';
    }
  }

  // Modal Confirm & Enviar para Otimização
  function handleModalConfirmSubmit() {
    const cv = state.cvText || modalCvText.value.trim();
    const job = state.jobText || modalJobText.value.trim();
    const jobUrl = modalJobUrl.value.trim();
    const linkedin = modalLinkedin.value.trim();
    const experience = modalExperience.value;

    if (!cv && !job && !jobUrl) {
      showToast('Por favor, adicione seu currículo e os detalhes da vaga.', 'error');
      return;
    }

    if (!cv) {
      showToast('Envie ou cole seu currículo atual antes de prosseguir.', 'error');
      return;
    }

    if (!job && !jobUrl) {
      showToast('Informe a descrição ou o link da vaga pretendida.', 'error');
      return;
    }

    state.cvText = cv;
    if (job) state.jobText = job;
    if (jobUrl) state.jobUrl = jobUrl;

    updateFilesSidebar();
    closeModal();

    // Monta o prompt profundo de envio
    let promptContent = `Olá VagasFilter! Gostaria de uma adaptação sênior e cirúrgica do meu currículo com padrão ouro para ATS para a seguinte vaga:\n\n`;
    promptContent += `### 📄 MEU CURRÍCULO:\n${cv}\n\n`;
    
    if (job) {
      promptContent += `### 🎯 DESCRIÇÃO DA VAGA:\n${job}\n\n`;
    } else if (jobUrl) {
      promptContent += `### 🌐 LINK DA VAGA:\n${jobUrl}\n\n`;
    }

    const extras = [];
    if (experience) extras.push(`- Nível de Experiência: ${experience}`);
    if (linkedin) extras.push(`- LinkedIn: ${linkedin}`);
    if (extras.length) promptContent += `### ℹ️ INFORMAÇÕES EXTRAS:\n${extras.join('\n')}\n\n`;

    promptContent += `Por favor, atue como um Recrutador Executivo Sênior e apresente a análise completa nas 7 seções com o currículo hiperpersonalizado para a vaga!`;

    // Adiciona bolha de usuário com os cards de anexo (idêntico à imagem de referência)
    addUserBubbleWithAttachments(promptContent);
  }

  // Enviar mensagem normal da barra de texto
  function handleUserSendMessage() {
    const text = chatInput.value.trim();
    if (!text || state.isThinking) return;

    chatInput.value = '';
    sendCustomUserPrompt(text);
  }

  // Pipeline de Envio para a API do Groq
  async function sendCustomUserPrompt(promptContent, displayPreview = null) {
    if (state.isThinking) return;

    const userDisplayText = displayPreview || promptContent;
    addMessageToChat('user', userDisplayText);

    state.messages.push({ role: 'user', content: promptContent });
    executeChatPipeline();
  }

  async function executeChatPipeline() {
    state.isThinking = true;
    sendBtn.disabled = true;

    // Atualiza stepper para Passo 3 (Personalizando o currículo)
    state.currentStep = 3;
    updateStepperUI();

    // Insere bolha do assistente com feedback animado (como na referência)
    const assistantRow = document.createElement('div');
    assistantRow.className = 'chat-row assistant';
    assistantRow.id = 'temp-assistant-row';

    const avatar = document.createElement('div');
    avatar.className = 'chat-msg-avatar';
    avatar.innerHTML = '<i class="fa-solid fa-robot"></i>';

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.innerHTML = `
      <p>Perfeito! Já estou analisando seu currículo e a descrição da vaga.</p>
      <p>Vou extrair as principais competências, alinhar a linguagem aos filtros de ATS e destacar suas experiências mais relevantes para essa oportunidade.</p>
      <div class="processing-pill">
        <div class="left-anim">
          <i class="fa-solid fa-circle-notch spinner"></i>
          <span>Analisando currículo e vaga...</span>
        </div>
        <span class="time-estimate">Em alguns segundos</span>
      </div>
      <div class="msg-timestamp">${getCurrentTime()}</div>
    `;

    assistantRow.appendChild(avatar);
    assistantRow.appendChild(bubble);
    chatMessagesEl.appendChild(assistantRow);
    scrollToBottom();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: state.messages,
          cv_text: state.cvText,
          job_text: state.jobText,
          job_url: state.jobUrl
        })
      });

      const rawText = await response.text();
      let data;
      try {
        data = JSON.parse(rawText);
      } catch (jsonErr) {
        throw new Error(`Resposta do servidor inválida (${response.status}): ${rawText.slice(0, 100)}`);
      }

      if (!response.ok || !data.success) {
        throw new Error(data.error || `Erro de processamento (${response.status})`);
      }

      // Salva URL do PDF gerado pelo pipeline
      if (data.pdf_url) {
        state.lastPdfUrl = data.pdf_url;
      }

      // Remove bolha temporária e renderiza resposta final completa
      assistantRow.remove();

      // Bolha de conclusão
      const completionIntro = `Pronto! Seu currículo personalizado foi auditado com fidelidade absoluta aos dados originais e gerado em padrão ouro para ATS.\nVocê pode copiar, baixar em .txt ou baixar o PDF oficial amigável para ATS abaixo:`;
      addMessageToChat('assistant', `${completionIntro}\n\n${data.reply}`, data.pdf_url);

      state.messages.push({ role: 'assistant', content: data.reply });

      // Atualiza stepper para Passo 4 (Resultado final)
      state.currentStep = 4;
      updateStepperUI();
      showToast('Currículo adaptado e auditado com sucesso!', 'success');

    } catch (err) {
      console.error("Erro no chat:", err);
      assistantRow.remove();
      addMessageToChat('assistant', `⚠️ **Aviso:** Não foi possível concluir a análise (${err.message}). Por favor, tente enviar novamente.`);
      showToast(err.message, 'error');
    } finally {
      state.isThinking = false;
      sendBtn.disabled = false;
      scrollToBottom();
    }
  }

  // Renderiza bolha do usuário com os cards de anexo (estilo imagem de referência)
  function addUserBubbleWithAttachments(promptContent) {
    state.messages.push({ role: 'user', content: promptContent });

    const row = document.createElement('div');
    row.className = 'chat-row user';

    const avatar = document.createElement('div');
    avatar.className = 'chat-msg-avatar';
    avatar.innerHTML = '<i class="fa-solid fa-user"></i>';

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';

    let attachmentsHtml = '';
    if (state.cvFileName) {
      attachmentsHtml += `
        <div class="bubble-attachment-card">
          <div class="file-side">
            <div class="file-icon pdf"><i class="fa-solid fa-file-pdf"></i></div>
            <div>
              <div class="file-name">${state.cvFileName}</div>
              <div class="file-meta">${state.cvFileSize || 'Documento'}</div>
            </div>
          </div>
        </div>
      `;
    }

    if (state.jobUrl || state.jobText) {
      const jobDesc = state.jobUrl || 'Descrição da vaga enviada';
      attachmentsHtml += `
        <div class="bubble-attachment-card">
          <div class="file-side">
            <div class="file-icon link"><i class="fa-solid fa-link"></i></div>
            <div>
              <div class="file-name">${jobDesc}</div>
              <div class="file-meta">Descrição da vaga</div>
            </div>
          </div>
        </div>
      `;
    }

    bubble.innerHTML = `
      ${attachmentsHtml}
      <p style="margin-top:6px;">Aqui estão meu currículo e a descrição da vaga!</p>
      <div class="msg-timestamp">${getCurrentTime()} <i class="fa-solid fa-check-double" style="color:var(--primary-green);"></i></div>
    `;

    row.appendChild(avatar);
    row.appendChild(bubble);
    chatMessagesEl.appendChild(row);
    scrollToBottom();

    // Executa pipeline
    executeChatPipeline();
  }

  // Inserção de Mensagem Genérica no Chat
  function addMessageToChat(role, text, pdfUrl = null) {
    const row = document.createElement('div');
    row.className = `chat-row ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'chat-msg-avatar';
    avatar.innerHTML = role === 'assistant' 
      ? '<i class="fa-solid fa-robot"></i>' 
      : '<i class="fa-solid fa-user"></i>';

    const bubble = document.createElement('div');
    bubble.className = `chat-bubble ${role === 'assistant' ? 'markdown-body' : ''}`;

    if (role === 'assistant') {
      bubble.innerHTML = formatAssistantContent(text, pdfUrl);
      attachActionButtons(bubble);
    } else {
      bubble.textContent = text;
    }

    const timeSpan = document.createElement('div');
    timeSpan.className = 'msg-timestamp';
    timeSpan.textContent = getCurrentTime();
    bubble.appendChild(timeSpan);

    row.appendChild(avatar);
    row.appendChild(bubble);
    chatMessagesEl.appendChild(row);
    scrollToBottom();
  }

  // Formatador da resposta do Assistente com Card de Currículo Adaptado
  function formatAssistantContent(rawText, pdfUrl = null) {
    let html = md.render(rawText);

    // Captura da Seção 3: Currículo adaptado
    const sectionRegex = /(<(?:h[2-4]|p|strong)[^>]*>[\s\S]*?3\.\s*Currículo adaptado[\s\S]*?<\/(?:h[2-4]|p|strong)>)([\s\S]*?)(?=<(?:h[2-4]|p|strong)[^>]*>[\s\S]*?4\.\s*O que foi alterado|$)/i;
    const match = html.match(sectionRegex);

    if (match) {
      const headerHtml = match[1];
      const resumeHtml = match[2];

      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = resumeHtml;
      const plainResume = tempDiv.innerText.replace(/```/g, '').trim();
      const currentPdf = pdfUrl || state.lastPdfUrl || '';

      const customCard = `
        ${headerHtml}
        <div class="adapted-resume-container">
          <div class="adapted-resume-header">
            <span class="adapted-tag"><i class="fa-solid fa-file-shield"></i> Padrão ATS Otimizado (Auditado com Zero Alucinação)</span>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
              <button type="button" class="btn-copy-resume" data-copy="${encodeURIComponent(plainResume)}">
                <i class="fa-regular fa-copy"></i> Copiar
              </button>
              <button type="button" class="btn-download-resume btn-copy-resume" style="background:#0f172a;" data-text="${encodeURIComponent(plainResume)}">
                <i class="fa-solid fa-download"></i> Baixar (.txt)
              </button>
            </div>
          </div>
          <div class="adapted-resume-content">${plainResume}</div>
        </div>
      `;

      html = html.replace(sectionRegex, customCard);
    }

    return html;
  }

  // Vincular eventos de Cópia e Download
  function attachActionButtons(container) {
    // Copiar
    container.querySelectorAll('.btn-copy-resume:not(.btn-download-resume)').forEach(btn => {
      btn.addEventListener('click', () => {
        const textToCopy = decodeURIComponent(btn.getAttribute('data-copy'));
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(textToCopy).then(() => {
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Copiado!';
            btn.style.background = '#0f172a';
            showToast('Currículo adaptado copiado para a área de transferência!', 'success');
            setTimeout(() => {
              btn.innerHTML = originalHtml;
              btn.style.background = '';
            }, 3000);
          }).catch(() => fallbackCopy(textToCopy, btn));
        } else {
          fallbackCopy(textToCopy, btn);
        }
      });
    });

    // Baixar .txt
    container.querySelectorAll('.btn-download-resume').forEach(btn => {
      btn.addEventListener('click', () => {
        const text = decodeURIComponent(btn.getAttribute('data-text'));
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'Curriculo_Otimizado_VagasFilter.txt';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        showToast('Download do currículo (.txt) iniciado!', 'success');
      });
    });
  }

  function fallbackCopy(text, btn) {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    btn.innerHTML = '<i class="fa-solid fa-check"></i> Copiado!';
    showToast('Currículo copiado com sucesso!', 'success');
  }

  // Atualizar visual do Stepper na Coluna Direita
  function updateStepperUI() {
    const steps = [
      { el: step1, num: 1 },
      { el: step2, num: 2 },
      { el: step3, num: 3 },
      { el: step4, num: 4 }
    ];

    steps.forEach(({ el, num }) => {
      el.classList.remove('done', 'active');
      if (num < state.currentStep) {
        el.classList.add('done');
      } else if (num === state.currentStep) {
        el.classList.add('active');
      }
    });
  }

  // Atualizar lista de arquivos na sidebar direita
  function updateFilesSidebar() {
    if (state.cvFileName) {
      badgeCvName.textContent = state.cvFileName;
      badgeCvMeta.textContent = state.cvFileSize || 'Documento pronto';
    }
    if (state.jobTitle || state.jobUrl) {
      badgeJobName.textContent = state.jobTitle || 'Vaga informada';
      badgeJobMeta.textContent = state.jobUrl ? `Link • ${extractDomain(state.jobUrl)}` : 'Texto da vaga pronto';
    }
  }

  function extractDomain(url) {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return 'web';
    }
  }

  // Gerenciamento do Modal
  function openModal() {
    modal.classList.remove('hidden');
  }

  function closeModal() {
    modal.classList.add('hidden');
  }

  function resetSession() {
    state.messages = [];
    state.cvText = '';
    state.cvFileName = '';
    state.cvFileSize = '';
    state.jobText = '';
    state.jobUrl = '';
    state.jobTitle = '';
    state.currentStep = 1;

    modalCvText.value = '';
    modalCvFile.value = '';
    modalJobUrl.value = '';
    modalJobText.value = '';
    cvDropLabel.textContent = 'Clique para selecionar PDF/TXT ou arraste aqui';

    badgeCvName.textContent = 'Nenhum currículo enviado';
    badgeCvMeta.textContent = 'Clique no clipe 📎 para anexar';
    badgeJobName.textContent = 'Nenhuma vaga informada';
    badgeJobMeta.textContent = 'Texto ou link da vaga';

    updateStepperUI();
    chatMessagesEl.innerHTML = '';
    loadInitialGreeting();
    showToast('Nova sessão iniciada!', 'info');
  }

  function getCurrentTime() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  }

  function scrollToBottom() {
    setTimeout(() => {
      chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    }, 50);
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    let icon = 'fa-circle-info';
    if (type === 'success') icon = 'fa-circle-check';
    if (type === 'error') icon = 'fa-circle-exclamation';

    toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${message}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3800);
  }
});
