# Software Aging Benchmark (DLSS)

Benchmark de estresse de GPU para estudar **software aging** em execuções longas (48 h por
teste) com DLSS e suas features. Feito sobre o projeto
[UE5-Benchmark](https://github.com/flyingllama87/UE5-Benchmark).

Este guia não pressupõe experiência com Unreal Engine ou C++.

## Sumário

1. [Como funciona](#1-como-funciona)
2. [Os 7 testes](#2-os-7-testes)
3. [Programas para instalar](#3-programas-para-instalar)
4. [Baixar o repositório e preparar o Python](#4-baixar-o-repositório-e-preparar-o-python)
5. [Completar o projeto Unreal: pasta Content](#5-completar-o-projeto-unreal-pasta-content)
6. [Plugin DLSS da NVIDIA](#6-plugin-dlss-da-nvidia)
7. [Compilar e empacotar](#7-compilar-e-empacotar)
8. [Validação rápida](#8-validação-rápida)
9. [Rodar a bateria de 48 h](#9-rodar-a-bateria-de-48-h)
10. [Resultados](#10-resultados)
11. [Relatório](#11-relatório)
12. [Análise de software aging (Mann-Kendall)](#12-análise-de-software-aging-mann-kendall)
13. [Cuidados de metodologia](#13-cuidados-de-metodologia)
14. [Alterar os testes ou o código](#14-alterar-os-testes-ou-o-código)
15. [Solução de problemas](#15-solução-de-problemas)
16. [Linux (Proton)](#16-linux-proton)

---

## 1. Como funciona

| Parte | Linguagem | O que faz |
|---|---|---|
| Jogo (`UE5Benchmark/`) | C++ (Unreal) | Roda a cena em loop, aplica as configurações de DLSS recebidas, mede FPS e tempos de frame a cada 5 s e fecha sozinho no fim do tempo |
| Orquestrador (`run.py`) | Python | Abre o jogo com a configuração de cada teste, confere se o DLSS ficou como pedido, mede o processo do jogo e a GPU, reabre o jogo se ele travar |
| Análise (`mann_kendall.py`) | Python | Teste de tendência sobre os resultados, rodado depois dos testes |

```
Software-Aging-Benchmark/
├── run.py                 ← comandos: list, check, build, package, run, report
├── mann_kendall.py        ← análise de software aging (depois dos testes)
├── requirements.txt
├── config/
│   ├── bench.json         ← caminhos, resolução, duração, intervalo de amostragem
│   └── tests.json         ← os 7 testes e as configurações de DLSS de cada um
├── bench/                 ← código Python (coleta, relatório, Mann-Kendall)
├── tests/validar_mann_kendall.py
├── UE5Benchmark/          ← projeto Unreal (o C++ do benchmark está em Source/Benchmark)
│   ├── Content/           ← NÃO vai para o Git (seção 5)
│   └── Plugins/           ← NÃO vai para o Git (seção 6)
└── BenchmarkRuns/         ← resultados, uma pasta por sessão
```

O jogo empacotado (`.exe`, vários GB) é gerado fora do repositório, em `C:\UE5BenchmarkBuild`.

---

## 2. Os 7 testes

| # | Nome | O que está ligado |
|---|---|---|
| 1 | `01_sem_dlss` | Nada (anti-aliasing padrão da engine, TSR, em resolução nativa) |
| 2 | `02_dlss` | DLSS em resolução nativa (DLAA) |
| 3 | `03_dlss_fg` | DLSS + Frame Generation |
| 4 | `04_dlss_rr` | DLSS + Ray Reconstruction |
| 5 | `05_dlss_sr` | DLSS + Super Resolution, modo Quality |
| 6 | `06_dlss_fg_rr` | DLSS + Frame Generation + Ray Reconstruction |
| 7 | `07_dlss_rr_sr` | DLSS + Ray Reconstruction + Super Resolution |

> **Por que "DLSS sem features" é o DLAA:** para a NVIDIA, a Super Resolution é o próprio
> núcleo do DLSS. O teste 2 roda a rede do DLSS na resolução nativa, sem reduzir resolução,
> sem gerar frames e sem substituir os denoisers. Para mudar essa definição, edite
> `config/tests.json` (seção 14).

---

## 3. Programas para instalar

Tudo é gratuito. Separe uns 150 GB de disco. Use as **mesmas versões** em todas as máquinas.

### 3.1 Driver da NVIDIA
Pelo NVIDIA App ou em <https://www.nvidia.com/drivers>. Anote a versão (ela também fica
registrada no `sessao.json` de cada sessão).

### 3.2 Unreal Engine 5.4
1. Instale o **Epic Games Launcher**: <https://store.epicgames.com/download> e entre com uma conta Epic.
2. **Unreal Engine → Biblioteca → +** ao lado de "Versões do motor" → escolha **5.4** → **Instalar** (~40 GB).
3. Pasta padrão: `C:\Program Files\Epic Games\UE_5.4` (é a que está no `bench.json`).

### 3.3 Compilador C++ (Build Tools 2022, MSVC 14.38)

A Unreal exige o compilador da Microsoft. O VS Code não compila C++ para ela.

> **Armadilhas:** o download padrão da Microsoft agora é o **Visual Studio 2026**, que a
> UE 5.4 não suporta. E o compilador mais novo do 2022 (14.44) **quebra** a UE 5.4; a 14.39 é
> bloqueada pela engine. A versão certa é a **14.38**.

1. Baixe o Build Tools **2022**: <https://aka.ms/vs/17/release/vs_buildtools.exe>
2. No PowerShell, abra o instalador já com os componentes certos:
   ```powershell
   cd $env:USERPROFILE\Downloads
   .\vs_buildtools.exe --add Microsoft.VisualStudio.Workload.VCTools `
     --add Microsoft.VisualStudio.Component.VC.14.38.17.8.x86.x64 `
     --add Microsoft.VisualStudio.Component.Windows11SDK.22621 `
     --add Microsoft.Net.Component.4.8.SDK
   ```
3. Confira no painel da direita: **MSVC v143 (v14.38-17.8)**, **SDK do Windows 11
   (10.0.22621.0)** e **SDK do .NET Framework 4.8** marcados; **MSVC (Mais recente)**
   desmarcado. Instale (~5 GB) e **reinicie**.
4. Em `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\`, anote o
   nome da pasta que começa com `14.38.` (ex.: `14.38.33130`).
5. Fixe esse compilador para a Unreal: crie (ou edite) o arquivo
   `%APPDATA%\Unreal Engine\UnrealBuildTool\BuildConfiguration.xml` (crie as pastas se não
   existirem) com o conteúdo abaixo, trocando o número pelo que você anotou:
   ```xml
   <?xml version="1.0" encoding="utf-8" ?>
   <Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
     <WindowsPlatform>
       <CompilerVersion>14.38.33130</CompilerVersion>
     </WindowsPlatform>
   </Configuration>
   ```

Na compilação, o log deve mostrar `Using Visual Studio 2022 14.38.xxxxx toolchain`.

### 3.4 Python, Git e VS Code
- Python **3.11 ou mais novo** (testado até o 3.14): <https://www.python.org/downloads/>.
  Marque **"Add python.exe to PATH"**.
- Git: <https://git-scm.com/download/win>.
- VS Code com a extensão **Python**.

### 3.5 Ajustes do Windows e da NVIDIA (em todas as máquinas)
- **NVIDIA App:** desligue qualquer *override* de DLSS (modelo/preset, modo do Frame
  Generation). Senão o driver troca o modelo por conta própria e as máquinas deixam de ser comparáveis.
- **Configurações → Sistema → Tela → Elementos gráficos:** ligue o **Agendamento de GPU
  acelerado por hardware** (o Frame Generation exige).
- Plano de energia **Alto desempenho**, atualizações do Windows pausadas, notificações
  desligadas, nenhum outro programa pesado aberto.

---

## 4. Baixar o repositório e preparar o Python

Use um caminho **curto, sem espaços nem acentos** e **fora do OneDrive** (a Unreal cria
pastas muito profundas e o OneDrive atrapalha arquivos abertos por 48 h):

```powershell
cd C:\
mkdir Pesquisa
cd Pesquisa
git clone <url-do-seu-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
code .
```

No terminal do VS Code (**Terminal → New Terminal**):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

O `activate` precisa ser repetido em todo terminal novo (aparece `(.venv)` no começo da
linha). Se o PowerShell bloquear scripts, rode uma vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Confira com `python run.py list` (mostra os 7 testes).

---

## 5. Completar o projeto Unreal: pasta Content

A pasta `UE5Benchmark/Content` (mapas e texturas, ~2,8 GB) não vai para o seu repositório:
ela não foi modificada e já está no repositório original, e o GitHub limita cada envio a
2 GB. Em cada máquina nova:

1. Na página do [UE5-Benchmark](https://github.com/flyingllama87/UE5-Benchmark), **Code → Download ZIP**.
2. Do zip, copie **só a pasta `Content`** para `UE5Benchmark\`
   (deve existir `UE5Benchmark\Content\BenchmarkLevel.umap`).

Não copie o resto do zip: `Source`, `Config` e o `.uproject` do repositório já têm as
modificações do benchmark (DirectX 12, ray tracing por hardware, plugins habilitados).

---

## 6. Plugin DLSS da NVIDIA

Também não vai para o GitHub (licença da NVIDIA e centenas de MB de binários).

> A página principal da NVIDIA só oferece o plugin para UE 5.5+. A versão para 5.4 está no
> [arquivo de versões anteriores](https://forums.developer.nvidia.com/t/nvidia-dlss-unreal-engine-plugin-archive/377564).
> O projeto usa o **DLSS 4.5 Plugin v8.6.1** (DLSS 310.6.0, Streamline 2.11.1). Use essa
> versão em todas as máquinas e cite-a no trabalho.

1. Com uma conta gratuita em <https://developer.nvidia.com>, baixe:
   <https://developer.nvidia.com/downloads/assets/gameworks/downloads/secure/dlss/ue-dlss-5.4/8.6.1/2026.05.21_ue5.4_dlss4.5plugin_v8.6.1.zip>
2. Copie **todas as subpastas** de `Plugins` do zip (`DLSS`, `NIS`, `Streamline*`, …) para
   `UE5Benchmark\Plugins\`. Deve existir `UE5Benchmark\Plugins\DLSS\DLSS.uplugin`.

**Atualizações automáticas (OTA) desligadas:** o driver baixa versões novas do DLSS e do
Frame Generation e, por padrão, o jogo carregaria essas versões no lugar das do plugin. O
`run.py` abre o jogo com `-slnoota` e `bAllowOTAUpdate=False` e avisa se o log da Unreal
ainda mostrar alguma OTA ativa (o teste fica marcado em `sessao.json`, campo `ota_ativa`).

Agora rode `python run.py check`: só o jogo empacotado deve faltar.

---

## 7. Compilar e empacotar

Com o Editor da Unreal **fechado**:

```powershell
python run.py build      # compila o C++ (alguns minutos). Termina com "Result: Succeeded"
python run.py package    # gera o .exe (de 30 min a 2 h; fica "parado" no cook, é normal)
```

Isso só é feito **uma vez, numa máquina Windows**. O Windows do laboratório e o Linux usam
a mesma pasta do jogo, copiada (veja o `COMANDOS.md`), e não precisam da Unreal.

O `package` termina com `BUILD SUCCESSFUL` e gera
`C:\UE5BenchmarkBuild\Windows\Benchmark\Binaries\Win64\Benchmark.exe`.

> Rode `build` e `package` de novo só quando mudar o C++ ou os plugins. Mudanças em
> `config/` **não** exigem reempacotar.

Para ver a cena no Editor (opcional): abra `UE5Benchmark\Benchmark.uproject`; na primeira
vez ele compila shaders por 10 a 40 min.

---

## 8. Validação rápida

Antes de qualquer bateria de 48 h, rode os 7 testes por 3 minutos cada (~30 min):

```powershell
python run.py run --tests all --minutes 3
```

Para cada teste o programa abre o jogo em tela cheia, confere se **cada** configuração de
DLSS ficou com o valor pedido e se a GPU suporta os recursos do teste. Se algo não bater,
**aborta aquele teste** e explica o motivo. No fim, todos devem aparecer como `completo`.

Confira também visualmente: no teste 5 (Super Resolution) o FPS sobe; no teste 3, o FPS
exibido fica bem acima do renderizado (Frame Generation exige RTX 40 ou mais nova).

---

## 9. Rodar a bateria de 48 h

7 testes × 48 h = **14 dias**, mais as pausas. Tudo de uma vez:

```powershell
python run.py run --tests all --hours 48
```

ou um teste por vez (permite usar o computador entre eles):

```powershell
python run.py run --tests 1 --hours 48
```

Durante o teste:
- O Windows é impedido de suspender ou desligar a tela.
- Se o jogo fechar sozinho, ele é reaberto com o tempo que falta (até `max_restarts` vezes).
- `Ctrl+C` interrompe; os dados gravados até ali ficam salvos.
- O `log.txt` da sessão é atualizado em tempo real.

---

## 10. Resultados

Cada sessão cria uma pasta em `BenchmarkRuns/`:

```
BenchmarkRuns/2026-10-21_09-30_windows/
├── sessao.json      ← máquina, versões, configuração e resultado de cada teste
├── log.txt          ← tudo o que aconteceu, em ordem
├── 01_sem_dlss.csv  ← uma linha a cada 5 s (um arquivo por teste)
├── 02_dlss.csv
└── logs/            ← logs da Unreal, só se algo deu errado (travamento, DLSS, OTA)
```

Enquanto o teste roda, os arquivos brutos do jogo ficam em `.tmp/` e são apagados no fim.
O CSV é gravado linha a linha: se o computador desligar no meio, o que já foi medido está salvo.

### Colunas do CSV

| Coluna | De onde vem | Significado |
|---|---|---|
| `timestamp_utc`, `horas` | | Momento da amostra e horas desde o início do teste |
| `execucao` | orquestrador | 1, 2, 3… muda quando o jogo foi reaberto após travar |
| `fps` | jogo | FPS médio renderizado nos últimos 5 s |
| `fps_exibido` | jogo (Streamline) | FPS na tela com Frame Generation (inclui frames gerados). Vazio sem FG |
| `frametime_p99_ms` | jogo | Tempo de frame no percentil 99 (travadas) |
| `gpu_time_ms`, `game_thread_ms`, `render_thread_ms` | jogo | Onde o tempo de cada frame é gasto: GPU ou threads de CPU |
| `proc_mem_mb` | sistema operacional | Memória física do jogo (Working Set) |
| `proc_private_mb` | sistema operacional | Memória alocada só pelo jogo (Private Bytes). **Principal sinal de vazamento**: o Working Set pode cair quando o Windows tira páginas da RAM, o Private Bytes não |
| `proc_threads`, `proc_handles` | sistema operacional | Threads e handles abertos pelo jogo (vazamento de recursos) |
| `proc_cpu_pct` | sistema operacional | CPU usada pelo jogo, em % da CPU inteira |
| `ram_mb`, `vram_mb` | sistema / NVML | RAM usada no sistema e VRAM usada na GPU |
| `gpu_util_pct`, `gpu_temp_c`, `gpu_clock_mhz`, `gpu_power_w` | NVML | Contexto: uso, temperatura, clock e potência da GPU |
| `throttle_power`, `throttle_thermal` | NVML | 1 = a GPU estava limitando o clock por potência / por temperatura |

As métricas do processo são medidas **de fora**, pelo sistema operacional, e não dependem do
que o jogo informa sobre si mesmo.

---

## 11. Relatório

Gráficos e resumo descritivo, só quando você pedir:

```powershell
python run.py report                                   # sessão mais recente
python run.py report BenchmarkRuns/2026-10-21_09-30_windows
python run.py report --all-sessions                    # junta todas (ex.: um teste por sessão)
```

Grava em `<sessão>/relatorio/` (ou `BenchmarkRuns/comparacao_<data>/` com várias sessões):

- `resumo.csv`: por teste, médias de FPS e tempos de frame, **início × fim** das métricas de
  aging (memória privada e física, handles, threads, VRAM, FPS), temperatura, clock,
  potência e % do tempo com limitação de potência/temperatura;
- `<teste>.png`: FPS, memória do jogo, handles, VRAM, temperatura e clock ao longo do tempo;
- `comparacao.png`: os testes lado a lado.

---

## 12. Análise de software aging (Mann-Kendall)

O `mann_kendall.py` só lê os resultados e grava a análise numa pasta nova. Não depende da
Unreal nem da GPU.

```powershell
python mann_kendall.py                 # todas as sessões em BenchmarkRuns/ (rótulo = windows/linux)
python mann_kendall.py --sessao BenchmarkRuns/2026-10-21_09-30_windows
python mann_kendall.py --sessao casa=BenchmarkRuns/sessao_A --sessao lab=D:/lab/sessao_B
```

Para comparar Windows e Linux, copie as pastas das sessões das duas plataformas para o
`BenchmarkRuns/` de um mesmo computador: o rótulo sai do `sessao.json` de cada uma.

### O que ele faz, para cada teste e métrica

1. **Descarta o aquecimento** (30 min) no início de cada execução do jogo: a alocação
   inicial e a compilação de shaders criam uma subida que não é envelhecimento.
2. **Separa as execuções** quando o jogo foi reaberto: o reinício zera o processo (é um
   "rejuvenescimento"), então cada execução é analisada à parte, além do teste completo.
3. **Agrega** em médias de 5 min (≈ 570 pontos em 48 h).
4. Aplica o **Mann-Kendall original** e com **correção de Hamed-Rao** para autocorrelação
   (a que decide, por padrão).
5. Calcula a **inclinação de Sen** por hora, com intervalo de confiança, e a variação total.
6. Diz se a tendência vai na direção do envelhecimento.

| Métrica | Envelhecimento se… |
|---|---|
| `proc_private_mb`, `proc_mem_mb`, `proc_handles`, `proc_threads`, `proc_cpu_pct`, `vram_mb`, `ram_mb` | sobe |
| `frametime_p99_ms`, `gpu_time_ms`, `game_thread_ms`, `render_thread_ms` | sobe |
| `fps`, `fps_exibido` | cai |
| `gpu_temp_c`, `gpu_clock_mhz`, `gpu_power_w`, `gpu_util_pct` | **contexto**: explicam a causa, não são envelhecimento |

Uma métrica que nunca muda (ex.: número de threads fixo) aparece como `constante`.

| Opção | Padrão | Significado |
|---|---|---|
| `--janela` | `5min` | Média por janela (`1min`, `15min`, `1h`…). `0` = sem agregação |
| `--aquecimento` | `30` | Minutos descartados no início de cada execução |
| `--alfa` | `0.05` | Nível de significância |
| `--metodo` | `hamed_rao` | Qual versão decide (`hamed_rao` ou `original`); as duas são calculadas |
| `--metricas` | todas | Lista separada por vírgula |
| `--saida` | `BenchmarkRuns/analises/mann_kendall_<data>` | Pasta de saída |
| `--csv` | | Analisar um CSV qualquer (com `--coluna-tempo` e `--colunas`) |

Para a validação de 3 min, use `--aquecimento 0 --janela 0`.

Saída: `mann_kendall_resultados.csv` (uma linha por rótulo × teste × execução × métrica),
`comparacao_entre_rotulos.csv` (Windows e Linux lado a lado), `parametros.json` (para citar
no trabalho) e `graficos/` (série agregada + reta de Sen).

### Como interpretar

1. **p < α indica tendência monotônica**, não a causa. O texto do trabalho é que conecta
   isso a software aging.
2. **Olhe o tamanho, não só o p-valor.** Em 48 h, tendências minúsculas ficam
   "significativas". Defina com o orientador um limiar prático (ex.: variação > X% em 48 h).
3. **"Recurso gasto para nada":** o padrão típico de aging é recurso subindo
   (`proc_private_mb`, `proc_handles`, `proc_cpu_pct`) enquanto o trabalho feito (`fps`) fica
   igual ou cai. Recurso subindo **junto** com FPS subindo não é aging.
4. **Separe aging de efeito térmico.** Se o FPS cai mas o clock também cai e a temperatura
   sobe (ou `throttle_thermal` aparece), a causa provável é a GPU se limitando. O resumo no
   terminal avisa.
5. **Reinícios:** o resultado de cada execução é o mais confiável; o "completo" mistura os
   dois lados do salto.
6. **Por que Hamed-Rao:** amostras de 5 s são autocorrelacionadas e o teste original assume
   independência (em dados simulados sem tendência, o original deu p = 0,00005; o corrigido,
   p = 0,16). As duas versões ficam na tabela.
7. **Muitas comparações:** várias métricas × 7 testes × 2 plataformas; com α = 0,05,
   espera-se ~5% de falsos positivos. Aplique uma correção (ex.: Bonferroni) ou declare a limitação.
8. **Windows × Linux:** no Linux todo frame passa pelo Proton; compare a **existência e o
   tamanho das tendências**, não os valores absolutos.

### Validação da implementação

`bench/mk_stats.py` foi conferido contra o **pyMannKendall** (Hussain & Mahmud, 2019): 36 de
36 casos idênticos (S, variância, Z, p, Hamed-Rao, Sen). Para repetir:
`pip install pymannkendall` e `python tests/validar_mann_kendall.py`.

### Referências

- Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica*, 13(3), 245–259.
- Kendall, M. G. (1975). *Rank Correlation Methods*. Griffin.
- Hamed, K. H.; Rao, A. R. (1998). A modified Mann-Kendall trend test for autocorrelated
  data. *Journal of Hydrology*, 204, 182–196.
- Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau.
  *Journal of the American Statistical Association*, 63, 1379–1389.
- Gilbert, R. O. (1987). *Statistical Methods for Environmental Pollution Monitoring*. Wiley.
- Hussain, M. M.; Mahmud, I. (2019). pyMannKendall: a python package for non parametric
  Mann Kendall family of trend tests. *Journal of Open Source Software*, 4(39), 1556.

---

## 13. Cuidados de metodologia

- **Mesmas condições:** mesma resolução, driver, build do jogo e, se possível, mesma
  temperatura ambiente (anote-a). Driver, GPU, CPU, versões da Unreal e do plugin ficam no `sessao.json`.
- **Resolução nativa do monitor** em `game.resolution` (ex.: `[2560, 1080]`).
- **Pausa entre testes** (`cooldown_minutes`, padrão 10): um teste não começa com a GPU já
  aquecida pelo anterior.
- **V-Sync e limite de FPS desligados** em todos os testes. No Painel de Controle NVIDIA,
  "Sincronização vertical" = "Usar configuração do aplicativo", sem limite de FPS global.
- **Frame Generation fixo em 2x** (`FramesToGenerate = 1`) em todos os testes com FG.
- **Versões do DLSS fixas:** confira `ota_ativa: false` em cada teste do `sessao.json`.
- **GPU no limite:** se `gpu_util_pct` ficar bem abaixo de ~95%, parte do tempo o gargalo é
  a CPU (veja `render_thread_ms`).
- **Ray Reconstruction:** o teste de RR desliga os denoisers da Unreal que a RR substitui
  (sombras e reflexos do Lumen), como faz a função oficial do plugin.

---

## 14. Alterar os testes ou o código

**Testes:** tudo em `config/tests.json`. Cada teste = `base_cvars` + `all_off` + as features
dele, nessa ordem. Exemplo, Super Resolution em Performance em vez de Quality:
```json
"sr": { "r.ScreenPercentage": "50" }
```
(66.7 = Quality, 58 = Balanced, 50 = Performance, 33.3 = Ultra Performance).
Confira com `python run.py list`. Não precisa reempacotar.

**Código C++:** fica em `UE5Benchmark/Source/Benchmark/`. Depois de editar, rode `build` e
`package`. Para autocompletar no VS Code: no Editor da Unreal, **Edit → Editor Preferences →
Source Code Editor = Visual Studio Code** e **Tools → Refresh Visual Studio Code Project**.

---

## 15. Solução de problemas

| Problema | Causa provável e solução |
|---|---|
| `Pasta Content vazia ou ausente` | Seção 5 |
| `Faltam plugins em ...Plugins` | Seção 6 |
| `cvar ... nao existe no jogo` | Plugin não habilitado ou nome diferente na sua versão. No jogo, abra o console (`'` ou `~`), digite `r.NGX` ou `r.Streamline` e veja as opções; corrija em `tests.json` |
| `Frame Generation nao esta disponivel: ...` | O motivo vem da NVIDIA. `NotSupportedIncompatibleHardware`: GPU anterior à RTX 40. `...HardwareSchedulingDisabled`: seção 3.5. `...DriverOutOfDate`: atualize o driver |
| `run_config.json sem o bloco 'support'` | O `.exe` é de uma versão antiga do código: `build` e `package` |
| `O jogo nao gravou o run_config.json` | A primeira abertura compila shaders; aumente `startup_timeout_s`. Veja o log em `logs/` |
| `has banned the MSVC 14.39` / `C4668 __has_feature` | Compilador errado: confira o `BuildConfiguration.xml` (seção 3.3) |
| `Could not find NetFxSDK install dir` | Falta o SDK do .NET Framework 4.8 (seção 3.3) |
| `Unable to build while Live Coding is active` | Feche o Editor da Unreal |
| Erro de caminho longo ao compilar | Caminho do repositório muito longo: use `C:\Pesquisa\...` e, se precisar, ative caminhos longos no Windows (`LongPathsEnabled`) |
| `check` não encontra a GPU | Atualize o driver e rode `pip install nvidia-ml-py` com o `.venv` ativo |
| Linux: DLSS aparece como não suportado | Confira `PROTON_ENABLE_NVAPI=1` no bloco `linux` e se o driver proprietário completo está instalado (o `check` procura a `nvngx.dll` do driver) |
| Linux: `O jogo nao gravou o run_config.json` na 1ª vez | A primeira abertura cria o prefixo do Wine e baixa o Steam Runtime: rode de novo |
| Erro de sintaxe em `bench.json` | A mensagem mostra a linha: confira aspas, vírgulas e chaves |

---

## 16. Linux (Proton)

O plugin DLSS da Unreal só existe para Windows, então no Linux roda o **mesmo
`Benchmark.exe`** compilado no Windows, traduzido pelo Proton:

| No Windows | No Linux (Proton) |
|---|---|
| DirectX 12 | VKD3D-Proton (DirectX 12 → Vulkan, inclusive o ray tracing) |
| NVAPI / DLSS do driver | DXVK-NVAPI → driver NVIDIA do Linux (`PROTON_ENABLE_NVAPI=1`) |

O orquestrador abre o jogo com o **umu-launcher** (`umu-run`), que roda o Proton fora da
Steam no mesmo ambiente que a Steam usaria. A instalação passo a passo está no
`COMANDOS.md` ("Preparar o Linux"). O bloco `linux` do `config/bench.json` diz onde estão o
jogo, o Proton e o prefixo do Wine.

O que muda no Linux:
- **Caminhos:** o jogo, dentro do Wine, enxerga o disco como `Z:`. O orquestrador converte
  sozinho.
- **Processo medido:** o `Benchmark.exe` dentro do Wine (não o lançador). `proc_handles`
  conta descritores de arquivo do Linux, e a memória é a do processo do Wine.
- **Versões fixas:** `UMU_RUNTIME_UPDATE=0` (o Steam Runtime não se atualiza no meio da
  pesquisa) e `PROTON_ENABLE_NGX_UPDATER=0` (o equivalente ao OTA desligado). A versão do
  Proton fica no `sessao.json`.
- **Suspensão:** bloqueada com `systemd-inhibit`. Se o log avisar que não conseguiu,
  desligue a suspensão nas configurações.
- **Conferências:** as mesmas do Windows. Se o Frame Generation ou o Ray Reconstruction não
  funcionarem pelo Proton naquela máquina, o teste é abortado com o motivo informado pela
  NVIDIA, e o teste também para se a Unreal desligar o ray tracing por hardware.

**Para comparar Windows × Linux:**
- Use a **mesma máquina** (dual boot), a mesma resolução e drivers da mesma série nas duas
  plataformas. Mantenha a mesma versão do Proton durante toda a pesquisa.
- Compare a **existência e o tamanho das tendências** (Mann-Kendall), não os valores
  absolutos: `proc_handles` e a memória do processo são medidos de jeitos diferentes
  em cada sistema.