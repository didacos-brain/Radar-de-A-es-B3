from __future__ import annotations

import io
import math
import warnings
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURAÇÃO PADRÃO — mantida a lógica do script original
# =============================================================================
CAPITAL_PADRAO = 50_000.00
ACOES_POR_METODOLOGIA_PADRAO = 2
QTD_ACOES_POR_LISTA_PADRAO = 10
LIQUIDEZ_MIN_PADRAO = 100_000.00
PREGOES_ZOOM_GRAFICO = 126  # aproximadamente 6 meses de pregões

METODOLOGIAS = {
    "EV/EBIT abaixo de 6": lambda df: df[(df["EV/EBIT"] > 0) & (df["EV/EBIT"] < 6.0)].sort_values("EV/EBIT", ascending=True),
    "P/VP abaixo de 0,60": lambda df: df[(df["P/VP"] > 0) & (df["P/VP"] < 0.60)].sort_values("P/VP", ascending=True),
    "Dividend Yield acima de 5%": lambda df: df[df["Div.Yield"] > 0.05].sort_values("Div.Yield", ascending=False),
    "PSR abaixo de 0,30": lambda df: df[(df["PSR"] > 0) & (df["PSR"] < 0.30)].sort_values("PSR", ascending=True),
    "P/L abaixo de 4": lambda df: df[(df["P/L"] > 0) & (df["P/L"] < 4.0)].sort_values("P/L", ascending=True),
}

st.set_page_config(
    page_title="Radar de Ações B3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1500px; }
      h1, h2, h3 { letter-spacing: -0.025em; }
      div[data-testid="stMetric"] { background: rgba(128,128,128,0.07); padding: .7rem .85rem; border-radius: 12px; }
      div[data-testid="stDataFrame"] { border-radius: 10px; }
      .subtle { color: #8994a5; font-size: .88rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📈 Radar de Ações B3")
st.caption("Filtros fundamentalistas, confirmação por média móvel de 200 pregões e análise de volume.")
st.info(
    "Ferramenta de triagem baseada nas regras configuradas. Os resultados dependem da disponibilidade e da qualidade dos dados externos e não constituem recomendação personalizada de investimento."
)


def converter_numero_br(serie: pd.Series) -> pd.Series:
    """Converte números em formato brasileiro; percentuais com '%' viram frações."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").astype(float)

    def converter(valor: Any) -> float:
        if pd.isna(valor):
            return float("nan")
        texto = str(valor).strip().replace("\xa0", "")
        if texto in {"", "-", "--", "N/A", "None"}:
            return float("nan")
        percentual = "%" in texto
        texto = texto.replace("%", "").replace(".", "").replace(",", ".")
        try:
            numero = float(texto)
            return numero / 100 if percentual else numero
        except ValueError:
            return float("nan")

    return serie.map(converter).astype(float)


@st.cache_data(ttl=1800, show_spinner=False)
def obter_dados_fundamentus() -> pd.DataFrame:
    url = "https://www.fundamentus.com.br/resultado.php"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    resposta = requests.get(url, headers=headers, timeout=30)
    resposta.raise_for_status()
    tabelas = pd.read_html(io.StringIO(resposta.text), decimal=",", thousands=".")
    if not tabelas:
        raise ValueError("O site não retornou uma tabela de ações.")

    df = tabelas[0].copy()
    colunas_obrigatorias = [
        "Papel", "Cotação", "P/L", "P/VP", "PSR", "Div.Yield", "EV/EBIT", "Liq.2meses"
    ]
    ausentes = [coluna for coluna in colunas_obrigatorias if coluna not in df.columns]
    if ausentes:
        raise ValueError("O formato retornado pelo Fundamentus mudou. Colunas ausentes: " + ", ".join(ausentes))

    for coluna in ["Cotação", "P/L", "P/VP", "PSR", "Div.Yield", "EV/EBIT", "Liq.2meses"]:
        df[coluna] = converter_numero_br(df[coluna])

    df["Papel"] = df["Papel"].astype(str).str.strip().str.upper()
    # Não restringir a letras antes do código numérico: alguns tickers válidos, como B3SA3,
    # contêm números também no radical. A tabela do Fundamentus já separa os ativos.
    df = df[df["Papel"].str.len().between(5, 6)].copy()
    return df


@st.cache_data(ttl=21600, show_spinner=False)
def obter_historico(papel: str) -> tuple[pd.DataFrame, str | None]:
    """Busca até dois anos de cotações; o cache evita consultar o mesmo ativo repetidamente."""
    try:
        dados = yf.Ticker(f"{papel}.SA").history(period="2y", auto_adjust=False)
        if dados is None or dados.empty:
            return pd.DataFrame(), "O provedor não retornou histórico para este ativo."
        dados = dados.copy()
        if isinstance(dados.columns, pd.MultiIndex):
            dados.columns = dados.columns.get_level_values(0)
        necessarias = {"Close", "Open", "Volume"}
        if not necessarias.issubset(set(dados.columns)):
            return pd.DataFrame(), "O histórico não contém todas as colunas esperadas."
        dados = dados.dropna(subset=["Close"])
        return dados, None
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def obter_metricas_e_historico(papel: str) -> dict[str, Any]:
    dados, erro = obter_historico(papel)
    if dados.empty or len(dados) < 200:
        mensagem = "SEM DADOS (menos de 200 pregões)" if not erro else f"ERRO NA CONSULTA: {erro}"
        return {
            "aprovada_sma": False,
            "Preco_YF": None,
            "SMA_200": None,
            "Gatilho_+10%": None,
            "Dist_SMA200_%": None,
            "Limite_2%_Vol_R$": None,
            "Status_SMA200+10%": mensagem,
            "historico": None,
        }

    dados["SMA200"] = dados["Close"].rolling(window=200).mean()
    dados["Gatilho_10pct"] = dados["SMA200"] * 1.10
    dados["Vol_MA60"] = dados["Volume"].rolling(window=60).mean()

    preco_atual = float(dados["Close"].iloc[-1])
    sma_200 = float(dados["SMA200"].iloc[-1])
    gatilho = float(dados["Gatilho_10pct"].iloc[-1])
    if not math.isfinite(sma_200) or sma_200 == 0:
        return {
            "aprovada_sma": False, "Preco_YF": round(preco_atual, 2), "SMA_200": None,
            "Gatilho_+10%": None, "Dist_SMA200_%": None, "Limite_2%_Vol_R$": None,
            "Status_SMA200+10%": "SEM DADOS PARA CALCULAR SMA200", "historico": dados,
        }

    dist_pct = ((preco_atual / sma_200) - 1.0) * 100.0
    vol_acoes_60d = float(dados["Vol_MA60"].iloc[-1])
    limite_2pct = vol_acoes_60d * preco_atual * 0.02 if math.isfinite(vol_acoes_60d) else 0.0
    aprovada_sma = preco_atual >= gatilho

    if aprovada_sma:
        status = "APROVADA (preço ≥ SMA200 + 10%)"
    elif preco_atual >= sma_200:
        status = "ACIMA DA SMA200, mas abaixo do gatilho +10%"
    else:
        status = "ABAIXO DA SMA200"

    return {
        "aprovada_sma": aprovada_sma,
        "Preco_YF": round(preco_atual, 2),
        "SMA_200": round(sma_200, 2),
        "Gatilho_+10%": round(gatilho, 2),
        "Dist_SMA200_%": round(dist_pct, 2),
        "Limite_2%_Vol_R$": round(limite_2pct, 2),
        "Status_SMA200+10%": status,
        "historico": dados,
    }


def aplicar_peneira_basica(df: pd.DataFrame, liquidez_minima: float) -> pd.DataFrame:
    filtrado = df[(df["P/L"] > 0) & (df["Liq.2meses"] >= liquidez_minima)].copy()
    filtrado["Radical"] = filtrado["Papel"].str[:4]
    return filtrado.sort_values("Liq.2meses", ascending=False).drop_duplicates(subset=["Radical"], keep="first").copy()


def executar_analise(
    capital_total: float,
    acoes_por_metodologia: int,
    qtd_acoes_por_lista: int,
    liquidez_minima: float,
    progress_callback=None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, dict[str, Any]], int]:
    bruto = obter_dados_fundamentus()
    df = aplicar_peneira_basica(bruto, liquidez_minima)
    rankings = {nome: funcao(df) for nome, funcao in METODOLOGIAS.items()}

    # Monta uma fila sem duplicar consultas históricas para o mesmo ticker.
    candidatos_por_metodo = {nome: rank.head(qtd_acoes_por_lista) for nome, rank in rankings.items()}
    papeis_unicos: list[str] = []
    for tabela in candidatos_por_metodo.values():
        for papel in tabela["Papel"].astype(str).tolist():
            if papel not in papeis_unicos:
                papeis_unicos.append(papel)

    metricas: dict[str, dict[str, Any]] = {}
    for idx, papel in enumerate(papeis_unicos, start=1):
        metricas[papel] = obter_metricas_e_historico(papel)
        if progress_callback:
            progress_callback(idx, len(papeis_unicos), papel)

    total_slots = len(METODOLOGIAS) * acoes_por_metodologia
    aporte_por_slot = capital_total / total_slots if total_slots else 0
    carteira: list[dict[str, Any]] = []
    acoes_selecionadas: list[dict[str, Any]] = []
    radicais_alocados: set[str] = set()
    slot_num = 1
    tabelas_top: dict[str, pd.DataFrame] = {}

    for nome_met, df_met in candidatos_por_metodo.items():
        linhas_met: list[dict[str, Any]] = []
        escolhidas_na_met = 0
        for pos, (_, row) in enumerate(df_met.iterrows(), start=1):
            papel = str(row["Papel"])
            radical = papel[:4]
            graf = metricas.get(papel) or obter_metricas_e_historico(papel)
            dist = graf["Dist_SMA200_%"]
            limite_volume = graf["Limite_2%_Vol_R$"] or 0
            linhas_met.append({
                "Rank": f"{pos}º",
                "Papel": papel,
                "Cotação Fundamentus (R$)": round(float(row["Cotação"]), 2) if pd.notna(row["Cotação"]) else None,
                "EV/EBIT": round(float(row["EV/EBIT"]), 2) if pd.notna(row["EV/EBIT"]) else None,
                "P/VP": round(float(row["P/VP"]), 2) if pd.notna(row["P/VP"]) else None,
                "Dividend Yield (%)": round(float(row["Div.Yield"]) * 100, 2) if pd.notna(row["Div.Yield"]) else None,
                "PSR": round(float(row["PSR"]), 2) if pd.notna(row["PSR"]) else None,
                "P/L": round(float(row["P/L"]), 2) if pd.notna(row["P/L"]) else None,
                "Liquidez 2 meses (R$)": float(row["Liq.2meses"]) if pd.notna(row["Liq.2meses"]) else None,
                "SMA 200 (R$)": graf["SMA_200"],
                "Gatilho +10% (R$)": graf["Gatilho_+10%"],
                "Distância da SMA200 (%)": dist,
                "Limite estimado 2% volume/dia (R$)": graf["Limite_2%_Vol_R$"],
                "Status técnico": graf["Status_SMA200+10%"],
            })

            if (
                escolhidas_na_met < acoes_por_metodologia
                and graf["aprovada_sma"]
                and limite_volume >= aporte_por_slot
                and radical not in radicais_alocados
            ):
                radicais_alocados.add(radical)
                escolhidas_na_met += 1
                item = {
                    "Vaga": f"Vaga {slot_num:02d}",
                    "Metodologia": nome_met,
                    "Ativo escolhido": papel,
                    "Posição no ranking": f"{pos}º",
                    "Cotação (R$)": graf["Preco_YF"],
                    "Distância da SMA200 (%)": f"{dist:+.2f}%" if dist is not None else "—",
                    "EV/EBIT": round(float(row["EV/EBIT"]), 2) if pd.notna(row["EV/EBIT"]) else None,
                    "P/VP": round(float(row["P/VP"]), 2) if pd.notna(row["P/VP"]) else None,
                    "Dividend Yield (%)": round(float(row["Div.Yield"]) * 100, 2) if pd.notna(row["Div.Yield"]) else None,
                    "PSR": round(float(row["PSR"]), 2) if pd.notna(row["PSR"]) else None,
                    "P/L": round(float(row["P/L"]), 2) if pd.notna(row["P/L"]) else None,
                    "Regra de seleção": "Passou pelos filtros definidos",
                }
                carteira.append(item)
                acoes_selecionadas.append({
                    "Vaga": item["Vaga"],
                    "Metodologia": nome_met,
                    "Ativo escolhido": papel,
                    "Distância da SMA200 (%)": item["Distância da SMA200 (%)"],
                })
                slot_num += 1

        while escolhidas_na_met < acoes_por_metodologia:
            carteira.append({
                "Vaga": f"Vaga {slot_num:02d}",
                "Metodologia": nome_met,
                "Ativo escolhido": "Tesouro Selic / renda fixa de curto prazo",
                "Posição no ranking": "—",
                "Cotação (R$)": None,
                "Distância da SMA200 (%)": "—",
                "EV/EBIT": None,
                "P/VP": None,
                "Dividend Yield (%)": None,
                "PSR": None,
                "P/L": None,
                "Regra de seleção": "Sem ativo elegível suficiente nesta metodologia",
            })
            escolhidas_na_met += 1
            slot_num += 1
        tabelas_top[nome_met] = pd.DataFrame(linhas_met)

    df_carteira = pd.DataFrame(carteira)
    return tabelas_top, df_carteira, metricas, len(df)


def grafico_tecnico(papel: str, info: dict[str, Any]) -> go.Figure | None:
    dados = info.get("historico")
    if dados is None or dados.empty:
        return None
    zoom = dados.tail(PREGOES_ZOOM_GRAFICO).copy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Close"], mode="lines", name="Cotação", line=dict(color="#38BDF8", width=2.4)))
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["SMA200"], mode="lines", name="SMA 200", line=dict(color="#F59E0B", width=1.8)))
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Gatilho_10pct"], mode="lines", name="Gatilho +10%", line=dict(color="#10B981", width=1.6, dash="dash")))
    fig.update_layout(
        title=f"{papel} · Cotação, SMA 200 e gatilho +10%",
        height=360,
        margin=dict(l=8, r=8, t=55, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Preço (R$)",
        hovermode="x unified",
    )
    return fig


def grafico_volume(papel: str, info: dict[str, Any]) -> go.Figure | None:
    dados = info.get("historico")
    if dados is None or dados.empty:
        return None
    zoom = dados.tail(PREGOES_ZOOM_GRAFICO).copy()
    cores = ["#10B981" if c >= o else "#EF4444" for c, o in zip(zoom["Close"], zoom["Open"])]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=zoom.index, y=zoom["Volume"] / 1000, name="Volume (mil ações)", marker_color=cores, opacity=0.65))
    fig.add_trace(go.Scatter(x=zoom.index, y=zoom["Vol_MA60"] / 1000, mode="lines", name="Média de 60 pregões", line=dict(color="#FACC15", width=2)))
    fig.update_layout(
        title=f"{papel} · Volume negociado",
        height=260,
        margin=dict(l=8, r=8, t=45, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Mil ações",
        hovermode="x unified",
    )
    return fig


def grafico_comparativo(papeis: list[str], metricas: dict[str, dict[str, Any]]) -> go.Figure | None:
    fig = go.Figure()
    algum = False
    for papel in papeis:
        info = metricas.get(papel, {})
        dados = info.get("historico")
        if dados is None or dados.empty:
            continue
        zoom = dados.tail(PREGOES_ZOOM_GRAFICO)
        serie = (zoom["Close"] / zoom["Close"].iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(x=serie.index, y=serie, mode="lines", name=papel, line=dict(width=2)))
        algum = True

    try:
        ibov = yf.Ticker("^BVSP").history(period="1y", auto_adjust=False).tail(PREGOES_ZOOM_GRAFICO)
        if not ibov.empty:
            serie_ibov = (ibov["Close"] / ibov["Close"].iloc[0] - 1) * 100
            fig.add_trace(go.Scatter(x=serie_ibov.index, y=serie_ibov, mode="lines", name="Ibovespa", line=dict(color="#64748B", dash="dash", width=2.5)))
            algum = True
    except Exception:
        pass

    if not algum:
        return None
    fig.add_hline(y=0, line_dash="dot", line_color="#64748B")
    fig.update_layout(
        title="Variação acumulada nos últimos ~6 meses",
        height=420,
        margin=dict(l=8, r=8, t=55, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis_title=None,
        yaxis_title="Variação (%)",
        hovermode="x unified",
    )
    return fig


# =============================================================================
# INTERFACE
# =============================================================================
with st.sidebar:
    st.header("⚙️ Parâmetros da análise")
    capital_total = st.number_input("Capital total da carteira (R$)", min_value=100.0, value=CAPITAL_PADRAO, step=1000.0)
    acoes_por_metodologia = st.number_input("Vagas por metodologia", min_value=1, max_value=5, value=ACOES_POR_METODOLOGIA_PADRAO, step=1)
    qtd_acoes_por_lista = st.slider("Candidatas analisadas por metodologia", min_value=3, max_value=10, value=QTD_ACOES_POR_LISTA_PADRAO)
    liquidez_minima = st.number_input("Liquidez mínima em 2 meses (R$)", min_value=0.0, value=LIQUIDEZ_MIN_PADRAO, step=25000.0)
    forcar_atualizacao = st.checkbox("Forçar nova coleta dos dados", value=False, help="Limpa o cache antes de consultar novamente o Fundamentus e os históricos.")
    st.caption("A análise técnica exige, por padrão, ao menos 200 pregões de histórico.")

executar = st.button("🔎 Executar análise", type="primary", use_container_width=True)
if executar:
    if forcar_atualizacao:
        st.cache_data.clear()
    barra = st.progress(0, text="Conectando ao Fundamentus...")
    def atualizar_progresso(atual: int, total: int, papel: str) -> None:
        percentagem = int(atual / total * 100) if total else 100
        barra.progress(percentagem, text=f"Analisando histórico de {papel} ({atual}/{total})...")

    try:
        with st.spinner("Coletando fundamentos e calculando os filtros técnicos. A primeira consulta pode demorar."):
            tabelas_top, df_carteira, metricas, qtd_filtradas = executar_analise(
                float(capital_total),
                int(acoes_por_metodologia),
                int(qtd_acoes_por_lista),
                float(liquidez_minima),
                progress_callback=atualizar_progresso,
            )
        st.session_state["analise"] = {
            "tabelas_top": tabelas_top,
            "carteira": df_carteira,
            "metricas": metricas,
            "qtd_filtradas": qtd_filtradas,
            "capital_total": float(capital_total),
            "acoes_por_metodologia": int(acoes_por_metodologia),
            "aporte_por_slot": float(capital_total) / (len(METODOLOGIAS) * int(acoes_por_metodologia)),
            "executado_em": datetime.now().strftime("%d/%m/%Y às %H:%M"),
        }
        barra.progress(100, text="Análise concluída.")
    except Exception as exc:
        barra.empty()
        st.error(f"Não foi possível concluir a análise: {exc}")
        st.markdown("Confira sua conexão e tente novamente mais tarde. O Fundamentus ou o Yahoo Finance podem estar temporariamente indisponíveis ou limitar consultas automatizadas.")

analise = st.session_state.get("analise")
if not analise:
    st.markdown("### Como usar")
    st.markdown(
        "1. Abra **Parâmetros da análise** para ajustar o capital e os filtros.\n"
        "2. Toque em **Executar análise**.\n"
        "3. Navegue pelos rankings, pela carteira-modelo e pelos gráficos interativos."
    )
    st.caption("Dados consultados no Fundamentus e no Yahoo Finance. A disponibilidade dos serviços externos não é garantida.")
else:
    df_carteira = analise["carteira"]
    metricas = analise["metricas"]
    selecionadas = df_carteira.loc[
        df_carteira["Ativo escolhido"].notna()
        & ~df_carteira["Ativo escolhido"].astype(str).str.startswith("Tesouro Selic"),
        "Ativo escolhido",
    ].astype(str).tolist()
    aporte_por_slot = analise["aporte_por_slot"]

    st.caption(f"Última execução: {analise['executado_em']} · {analise['qtd_filtradas']} ações passaram pela peneira básica.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Capital configurado", f"R$ {analise['capital_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Aporte teórico por vaga", f"R$ {aporte_por_slot:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Ativos selecionados", f"{len(selecionadas)} de {len(df_carteira)} vagas")

    tab_carteira, tab_rankings, tab_graficos, tab_regras = st.tabs(["📋 Carteira-modelo", "🔍 Rankings", "📊 Gráficos", "ℹ️ Regras"])

    with tab_carteira:
        st.subheader("Distribuição sugerida pelas regras do sistema")
        st.dataframe(df_carteira, use_container_width=True, hide_index=True)
        csv_carteira = df_carteira.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Baixar carteira em CSV", data=csv_carteira, file_name="carteira_modelo_b3.csv", mime="text/csv", use_container_width=True)
        st.caption("Vagas preenchidas com renda fixa são marcadores da regra original quando não há ações elegíveis suficientes. Valide os dados e os critérios antes de tomar decisões.")

    with tab_rankings:
        st.subheader("Candidatas por metodologia")
        metodologia_escolhida = st.selectbox("Escolha a metodologia", list(analise["tabelas_top"].keys()))
        df_rank = analise["tabelas_top"][metodologia_escolhida]
        if df_rank.empty:
            st.warning("Nenhuma ação passou pelos critérios fundamentalistas desta metodologia.")
        else:
            st.dataframe(df_rank, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar este ranking em CSV",
                data=df_rank.to_csv(index=False).encode("utf-8-sig"),
                file_name="ranking_" + metodologia_escolhida.lower().replace(" ", "_").replace("/", "-") + ".csv",
                mime="text/csv",
                use_container_width=True,
                key="download_ranking",
            )

    with tab_graficos:
        st.subheader("Análise técnica dos ativos selecionados")
        papeis_com_historico = [p for p in selecionadas if metricas.get(p, {}).get("historico") is not None]
        if papeis_com_historico:
            papel_grafico = st.selectbox("Escolha uma ação", papeis_com_historico)
            info = metricas[papel_grafico]
            k1, k2, k3 = st.columns(3)
            k1.metric("Cotação", f"R$ {info['Preco_YF']:.2f}" if info["Preco_YF"] is not None else "—")
            k2.metric("SMA 200", f"R$ {info['SMA_200']:.2f}" if info["SMA_200"] is not None else "—")
            k3.metric("Distância da SMA 200", f"{info['Dist_SMA200_%']:+.2f}%" if info["Dist_SMA200_%"] is not None else "—")
            st.write("**Status técnico:** " + str(info["Status_SMA200+10%"]))
            fig_preco = grafico_tecnico(papel_grafico, info)
            fig_volume = grafico_volume(papel_grafico, info)
            if fig_preco:
                st.plotly_chart(fig_preco, use_container_width=True, config={"displayModeBar": False})
            if fig_volume:
                st.plotly_chart(fig_volume, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Nenhuma ação selecionada tem histórico suficiente para exibir gráficos técnicos.")

        st.divider()
        st.subheader("Comparativo de desempenho")
        if papeis_com_historico:
            if st.button("Gerar comparativo com Ibovespa", use_container_width=True):
                with st.spinner("Consultando o histórico do Ibovespa..."):
                    fig_comp = grafico_comparativo(papeis_com_historico, metricas)
                if fig_comp:
                    st.session_state["grafico_comparativo"] = fig_comp
                else:
                    st.warning("Não foi possível gerar o comparativo com os dados disponíveis.")
            if st.session_state.get("grafico_comparativo"):
                st.plotly_chart(st.session_state["grafico_comparativo"], use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("O comparativo ficará disponível quando houver ativos selecionados com histórico válido.")

    with tab_regras:
        st.subheader("Critérios aplicados")
        st.markdown(
            "- **Peneira básica:** P/L positivo, liquidez mínima configurada e manutenção do papel mais líquido por radical de quatro letras.\n"
            "- **EV/EBIT:** maior que zero e menor que 6.\n"
            "- **P/VP:** maior que zero e menor que 0,60.\n"
            "- **Dividend Yield:** acima de 5%.\n"
            "- **PSR:** maior que zero e menor que 0,30.\n"
            "- **P/L:** maior que zero e menor que 4.\n"
            "- **Confirmação técnica:** cotação igual ou superior a 110% da média móvel simples de 200 pregões.\n"
            "- **Filtro de volume:** limite calculado como 2% do volume financeiro médio estimado a partir da média de volume de 60 pregões e da cotação recente.\n"
            "- **Diversificação entre métodos:** evita alocar mais de um papel com o mesmo radical de quatro letras.\n"
            "- **Vagas não preenchidas:** são identificadas como renda fixa de curto prazo, conforme a lógica do código original."
        )
        st.caption("Os critérios são regras do seu algoritmo, não uma garantia de desempenho futuro. Cotação, fundamentos e históricos podem apresentar atraso, inconsistência ou indisponibilidade.")

st.divider()
st.caption("Radar de Ações B3 · Interface web adaptável para celular · Fontes externas: Fundamentus e Yahoo Finance")
