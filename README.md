# Radar de Ações B3 — Webapp para iPhone

Este projeto transforma o script de análise de ações em uma interface web com tabelas, carteira-modelo, rankings por metodologia, gráficos interativos e exportação CSV.

## O que preserva do algoritmo original

- Peneira básica: P/L positivo, liquidez mínima e escolha do papel mais líquido por radical de quatro letras.
- Cinco metodologias fundamentalistas: EV/EBIT, P/VP, Dividend Yield, PSR e P/L.
- Confirmação técnica por SMA de 200 pregões e gatilho de +10%.
- Filtro de volume baseado na média de volume de 60 pregões.
- Configuração inicial de R$ 50.000, duas vagas por metodologia e análise das dez primeiras candidatas por método.
- Gráficos de cotação, SMA 200, gatilho, volume e comparativo de desempenho.

Os valores de configuração podem ser alterados no menu lateral.

## Publicar gratuitamente com Streamlit Community Cloud

1. Crie uma conta no GitHub: https://github.com/
2. Crie um repositório para o projeto e envie estes arquivos: `streamlit_app.py`, `requirements.txt`, `README.md` e a pasta `.streamlit`.
3. Acesse https://share.streamlit.io/ e entre com sua conta GitHub.
4. Clique em **Create app** e selecione o repositório, a branch (`main`) e o arquivo principal `streamlit_app.py`.
5. Clique em **Deploy**. O serviço instala as dependências listadas no `requirements.txt`.
6. Abra o endereço `*.streamlit.app` no Safari do iPhone.
7. No Safari, toque em **Compartilhar** → **Adicionar à Tela de Início**. Se a opção aparecer, ative **Abrir como App Web**.

Consulte o guia oficial: https://docs.streamlit.io/deploy/streamlit-community-cloud

## Executar no computador antes de publicar (opcional)

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Limitações importantes

- O app consulta dados de terceiros (Fundamentus e Yahoo Finance). Se algum serviço bloquear ou mudar sua página/API, a consulta poderá falhar até que o código seja ajustado.
- O cache reduz consultas repetidas; use a opção **Forçar nova coleta dos dados** no menu lateral quando quiser limpar o cache da sessão/servidor antes de executar.
- A versão gratuita do Community Cloud pode colocar apps em repouso por inatividade. A primeira abertura depois disso pode demorar.
- Não coloque senhas, tokens, credenciais ou informações financeiras pessoais no código ou no repositório.
- As saídas reproduzem critérios algorítmicos definidos no código; não são recomendação personalizada de investimento nem garantia de resultados.
