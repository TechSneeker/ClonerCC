# ClonerCC

Aplicação desktop em Python para coletar, baixar e pós-processar vídeos de perfis do TikTok, com interface gráfica, persistência em SQLite e um pipeline de normalização de metadados de vídeo.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-automação-2EAD33?logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-persistência-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

## Sobre o projeto

O ClonerCC nasceu como um estudo prático de automação de navegador e de processamento de mídia em lote. Ele percorre um perfil público do TikTok, coleta as URLs e descrições dos vídeos, baixa os arquivos e mantém o estado de cada item em um banco local, de forma que a coleta seja incremental: rodar de novo só traz o que é novo.

A parte mais interessante do ponto de vista técnico é a combinação de três mundos em um app só: automação de navegador headful com evasão de detecção (Playwright + stealth), um pipeline de linha de comando para mídia (ffmpeg e exiftool) e uma GUI responsiva que não trava durante operações longas, graças ao uso de threads com uma fila de log para comunicação com a interface.

O projeto roda inteiramente na máquina do usuário. A autenticação é feita com cookies exportados do próprio navegador, e nenhum dado é enviado para serviços de terceiros.

> **Aviso de uso.** Esta é uma ferramenta de estudo. Baixar e redistribuir conteúdo de terceiros pode violar os Termos de Uso da plataforma e direitos autorais. Use apenas com conteúdo próprio ou com autorização, e por sua conta e risco.

## Tecnologias

- **Python 3.10+** (uso extensivo de type hints e sintaxe moderna)
- **Playwright** + **tf-playwright-stealth** para automação de navegador com evasão de detecção
- **yt-dlp** para o download dos vídeos
- **SQLite** (via `sqlite3` da biblioteca padrão) para persistência e coleta incremental
- **customtkinter** / **Tkinter** para a interface gráfica
- **Pillow** para manipulação de imagens na GUI
- **ffmpeg** e **exiftool** (binários externos) para o pipeline de metadados

## Funcionalidades

- **Coleta incremental** de URLs e descrições de um perfil, com scroll automático e detecção de captcha (pausa e pede resolução manual).
- **Download em lote** com acompanhamento de progresso e gravação de descrição em arquivo sidecar `.txt` ao lado de cada vídeo.
- **Banco de dados local** com status por vídeo (`pending`, `downloaded`, `error`, `cleared`) e uma aba de gerenciamento na GUI (filtrar, listar, apagar, resetar erros, re-buscar descrições).
- **Pipeline de normalização de metadados** que reescreve o container para QuickTime e ajusta campos de metadados do arquivo, útil para padronizar a saída de vídeos de diferentes origens.
- **GUI não bloqueante**: operações longas rodam em threads separadas e transmitem o log para a interface via fila.

## Pré-requisitos

- Python 3.10 ou superior
- [ffmpeg](https://ffmpeg.org/download.html) no `PATH` (necessário para o pipeline de metadados)
- [exiftool](https://exiftool.org/) no `PATH` (necessário para o pipeline de metadados)
- Navegadores do Playwright instalados (passo abaixo)

## Instalação

```bash
# Clone o repositório
git clone https://github.com/<seu-usuario>/ClonerCC.git
cd ClonerCC

# (recomendado) crie um ambiente virtual
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

# Instale as dependências
pip install -r requirements.txt

# Baixe os navegadores usados pelo Playwright
playwright install chromium
```

## Configuração dos cookies

A coleta precisa de cookies de uma sessão autenticada do TikTok, exportados do seu navegador:

1. Instale a extensão **Cookie-Editor** no seu navegador.
2. Faça login no TikTok.
3. Em `https://www.tiktok.com`, abra o Cookie-Editor e use **Export → Export as JSON**.
4. Salve o arquivo como `cookies.json` na raiz do projeto (ou aponte para ele pela GUI).

O arquivo [`cookies.example.json`](cookies.example.json) mostra o formato esperado. **Nunca** versione o seu `cookies.json` real: ele contém tokens de sessão e já está no `.gitignore`.

## Como rodar

Interface gráfica (modo principal):

```bash
python app.py
```

No Windows também é possível usar os atalhos `start.bat` (com console) ou `start-silent.bat` (sem console).

A GUI tem duas abas:

- **Clonar**: informe o `@usuario`, o arquivo de cookies e a pasta de destino, depois use *Coletar tudo*, *Baixar* e *Limpar Metadados*.
- **Banco de Dados**: filtre por perfil/status, liste os registros e gerencie o banco.

Linha de comando (scraper):

```bash
# Coletar todas as URLs de um perfil
python scraper.py exemplo_usuario

# Coletar no máximo 50 e já baixar
python scraper.py exemplo_usuario --max 50 --download --output downloads

# Usar um arquivo de cookies específico
python scraper.py exemplo_usuario --cookies my_cookies.json
```

Pipeline de metadados isolado:

```bash
# Processa um arquivo ou uma pasta inteira de .mp4
python metadata_cleaner.py downloads
python metadata_cleaner.py video.mp4 -o saida.MOV
```

## Estrutura do projeto

```
ClonerCC/
├── app.py                # GUI (customtkinter): coleta, download e gerência do banco
├── scraper.py            # Automação Playwright: coleta URLs/descrições do perfil
├── downloader.py         # Download via yt-dlp + escrita de sidecar e atualização do banco
├── metadata_cleaner.py   # Pipeline ffmpeg/exiftool de normalização de metadados
├── db.py                 # Camada SQLite (modelo VideoRecord + operações)
├── requirements.txt
├── cookies.example.json  # Formato esperado do arquivo de cookies (sem valores reais)
└── docs/screenshots/     # Imagens usadas na documentação
```

## Decisões técnicas

- **Coleta incremental via banco.** Em vez de recoletar tudo a cada execução, o `scraper` consulta as URLs já conhecidas de um perfil e processa apenas as novas. O `upsert` nunca sobrescreve `status`, `file_path` ou `downloaded_at` de registros existentes, preservando o histórico de download.
- **GUI desacoplada do trabalho pesado.** Toda operação longa (scraping, download, metadados) roda em uma thread separada e envia saída para a interface por uma `queue.Queue`, que a GUI consome em um loop com `after()`. Isso mantém a janela responsiva e centraliza o log.
- **Pipeline de mídia em duas etapas.** O `ffmpeg` copia os streams sem reencode (rápido e sem perda) e troca o container; o `exiftool` ajusta os campos de metadados que o ffmpeg não grava de forma confiável.
- **Dependências externas isoladas.** O pipeline verifica a presença de `ffmpeg` e `exiftool` no `PATH` antes de rodar e falha com uma mensagem clara, em vez de quebrar no meio do processamento.

## Licença

Distribuído sob a licença MIT. Veja [`LICENSE`](LICENSE) para os termos completos.

<div align="center">
  <br>
  <br>
  <br>
  <br>
  <img src="docs/screenshots/logo.png" alt="Logo TechSneeker" width="240">
  <br>
  <sub>Made by <strong>TechSneeker</strong></sub>
</div>
