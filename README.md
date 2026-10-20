# DLSS GPU Stress Bench

Benchmark de estresse de GPU para testes longos (ex.: 48 h por teste) com DLSS e suas
features, construído sobre o projeto [UE5-Benchmark](https://github.com/flyingllama87/UE5-Benchmark).

Este guia parte do zero: não pressupõe que você já tenha usado Unreal Engine ou C++.

---

## Sumário

1. [Como o projeto funciona](#1-como-o-projeto-funciona)
2. [O que instalar](#2-o-que-instalar)
3. [Organizar as pastas e abrir no VS Code](#3-organizar-as-pastas-e-abrir-no-vs-code)
4. [Preparar o Python](#4-preparar-o-python)
5. [Configurar os caminhos](#5-configurar-os-caminhos)
6. [Abrir o projeto Unreal pela primeira vez](#6-abrir-o-projeto-unreal-pela-primeira-vez)
7. [Instalar o plugin DLSS](#7-instalar-o-plugin-dlss)
8. [Aplicar o código do benchmark e compilar](#8-aplicar-o-código-do-benchmark-e-compilar)
9. [Empacotar o jogo](#9-empacotar-o-jogo)
10. [Validação rápida (antes das 48 h)](#10-validação-rápida-antes-das-48-h)
11. [Rodar a bateria de verdade](#11-rodar-a-bateria-de-verdade)
12. [Arquivos de resultado](#12-arquivos-de-resultado)
13. [Cuidados de metodologia](#13-cuidados-de-metodologia)
14. [Alterar os testes](#14-alterar-os-testes)
15. [Solução de problemas](#15-solução-de-problemas)
16. [Análise de software aging (Mann-Kendall)](#16-análise-de-software-aging-mann-kendall)

---

## 1. Como o projeto funciona

O DLSS só pode ser ligado dentro de um motor gráfico, por isso existem duas partes:

| Parte | Linguagem | O que faz |
|---|---|---|
| Jogo (Unreal) | C++ | Roda a cena em loop, aplica as configurações de DLSS recebidas, grava FPS e tempos de frame a cada 5 s e fecha sozinho ao fim do tempo |
| Orquestrador | Python | Abre o jogo com a configuração de cada teste, confere se o DLSS ficou como pedido, monitora a GPU, reabre o jogo se ele travar e gera os gráficos |

Você **não precisa escrever C++**. Os arquivos C++ já estão prontos em `unreal/`, e um comando
Python copia esses arquivos para o projeto. Toda a operação do dia a dia é feita pelo
`run.py`.

### Estrutura

```
dlss-gpu-bench/
├── run.py                  ← comandos: check, apply, build, package, run, report
├── mann_kendall.py         ← análise de software aging, rodada DEPOIS dos testes
├── requirements.txt        ← bibliotecas Python
├── config/
│   ├── bench.json          ← caminhos, resolução, duração, intervalo de amostragem
│   └── tests.json          ← os 7 testes e as configurações de DLSS de cada um
├── bench/                  ← código Python do orquestrador
│   ├── config.py, runner.py, monitor.py, presentmon.py, report.py, ue_build.py
│   ├── mk_stats.py         ← teste de Mann-Kendall, Hamed-Rao e inclinação de Sen
│   └── aging.py            ← lê as sessões, prepara as séries, tabelas e gráficos
├── tests/validar_mann_kendall.py ← confere a implementação contra o pyMannKendall
└── unreal/Source/Benchmark/ ← arquivos C++ que substituem os do UE5-Benchmark
```

### Os 7 testes

| # | Nome | O que está ligado |
|---|---|---|
| 1 | `01_sem_dlss` | Nada (anti-aliasing padrão da engine, TSR, em resolução nativa) |
| 2 | `02_dlss` | DLSS em resolução nativa (DLAA) |
| 3 | `03_dlss_fg` | DLSS + Frame Generation (feature 1) |
| 4 | `04_dlss_rr` | DLSS + Ray Reconstruction (feature 2) |
| 5 | `05_dlss_sr` | DLSS + Super Resolution, modo Quality (feature 3) |
| 6 | `06_dlss_fg_rr` | DLSS + feature 1 + feature 2 |
| 7 | `07_dlss_rr_sr` | DLSS + feature 2 + feature 3 |

> **Por que "DLSS sem features" é o DLAA:** para a NVIDIA, a Super Resolution é o próprio
> núcleo do DLSS. Para ter um "DLSS básico" separado da Super Resolution, o teste 2 roda a
> rede do DLSS na resolução nativa, sem reduzir resolução, sem gerar frames e sem substituir
> os denoisers. Se o seu orientador definir de outro jeito, basta editar `config/tests.json`
> (seção 14), sem mexer em código.

---

## 2. O que instalar

Tudo é gratuito. Separe uns 150 GB de disco.

### 2.1 Driver da NVIDIA
Atualize pelo GeForce Experience / NVIDIA App ou em <https://www.nvidia.com/drivers>.
Anote a versão: ela deve ser a **mesma** em todos os testes.

### 2.2 Unreal Engine 5.4
1. Instale o **Epic Games Launcher**: <https://store.epicgames.com/download>
2. Entre com uma conta Epic (gratuita).
3. Aba **Unreal Engine → Biblioteca** → botão **+** ao lado de "Versões do motor".
4. Escolha **5.4** (o projeto foi feito nela) e clique em **Instalar**. São ~40 GB.
5. Anote a pasta de instalação (padrão: `C:\Program Files\Epic Games\UE_5.4`).

### 2.3 Compilador C++ da Microsoft (Build Tools)

O VS Code é só um **editor de texto**; ele não compila C++ para a Unreal. A Unreal exige o
compilador da Microsoft (MSVC). Você não precisa da IDE Visual Studio, só das ferramentas
de compilação (Build Tools).

> **Duas armadilhas:**
> - O download padrão da Microsoft agora é o **Visual Studio 2026**, que a UE 5.4 **não**
>   suporta. É preciso o **2022**.
> - O compilador mais novo do VS 2022 (14.44) **quebra** a compilação da UE 5.4, e a 14.39 é
>   bloqueada pela própria engine. A versão certa é a **14.38**.

**1. Baixe o Build Tools 2022** pelo link direto oficial da Microsoft (não precisa de login):
<https://aka.ms/vs/17/release/vs_buildtools.exe>

**2. Abra o instalador já com os componentes certos.** No PowerShell:

```powershell
cd $env:USERPROFILE\Downloads
.\vs_buildtools.exe --add Microsoft.VisualStudio.Workload.VCTools `
  --add Microsoft.VisualStudio.Component.VC.14.38.17.8.x86.x64 `
  --add Microsoft.VisualStudio.Component.Windows11SDK.22621 `
  --add Microsoft.Net.Component.4.8.SDK
```

Aceite a permissão de administrador. O Visual Studio Installer abre com tudo marcado.

**3. Confira antes de instalar.** No topo deve aparecer **Build Tools 2022** (não 2026). No
painel da direita, "Detalhes da instalação":

| Item | Estado |
|---|---|
| Desenvolvimento para desktop com C++ | marcado |
| MSVC v143 … (v14.38-17.8) | **marcado** (pode aparecer "fora de suporte"; é normal) |
| SDK do Windows 11 (10.0.22621.0) | **marcado** |
| SDK do .NET Framework 4.8 | **marcado** (o Editor da Unreal precisa dele) |
| MSVC v143 … **(Mais recente)** | **desmarcado** |

Clique em **Instalar** (~5 GB) e **reinicie o computador** no fim.

Se preferir marcar tudo à mão: na aba **Cargas de trabalho** marque "Desenvolvimento para
desktop com C++"; no painel da direita desmarque o MSVC "(Mais recente)" e marque o
"SDK do Windows 11 (10.0.22621.0)"; na aba **Componentes individuais** busque `14.38` e
marque o "MSVC v143 - VS 2022 C++ x64/x86 build tools (v14.38-17.8)".

**4. Confira a instalação.** Abra a pasta
`C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\`.
Deve haver uma pasta que começa com `14.38.` (ex.: `14.38.33130`). Anote o nome exato.

**5. Fixe esse compilador para a Unreal** (garante que todos os builds da pesquisa usem o
mesmo compilador, mesmo que outro seja instalado depois):

1. No Explorador de Arquivos, digite na barra de endereço `%APPDATA%\Unreal Engine\UnrealBuildTool`
   e aperte Enter. Se a pasta não existir, crie `Unreal Engine` e, dentro dela, `UnrealBuildTool`.
2. Crie (ou edite, se já existir) o arquivo `BuildConfiguration.xml` com o conteúdo abaixo,
   trocando `14.38.33130` pelo nome exato da pasta que você anotou:

```xml
<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
  <WindowsPlatform>
    <CompilerVersion>14.38.33130</CompilerVersion>
  </WindowsPlatform>
</Configuration>
```

Se o arquivo já existir com outro conteúdo, só acrescente o bloco `<WindowsPlatform>` dentro
de `<Configuration>`.

**6. Como confirmar depois:** quando a Unreal compilar pela primeira vez (seção 6), o log deve
mostrar uma linha parecida com
`Using Visual Studio 2022 14.38.33130 toolchain ... and Windows 10.0.22621.0 SDK`.

| Erro | Causa e solução |
|---|---|
| `has banned the MSVC 14.39...` | A 14.39 está instalada e foi escolhida: confira o passo 5 ou desinstale a 14.39 |
| `C4668: '__has_feature' is not defined` | A Unreal usou o compilador mais novo (14.4x): confira o passo 5 |
| `LNK1181: cannot open input file 'delayimp.lib'` | Instalações de versões diferentes misturadas: no instalador, desmarque todos os MSVC e deixe só o 14.38 |
| Unreal não encontra o Visual Studio | Foi instalado o Build Tools **2026**: instale o 2022 pelo link do passo 1 |
| `Could not find NetFxSDK install dir` | Falta o **SDK do .NET Framework 4.8**: no Visual Studio Installer, **Modificar** → **Componentes individuais** → marque "SDK do .NET Framework 4.8" |

### 2.4 Python
Instale o Python **3.11 ou mais novo** (testado até o 3.14) em <https://www.python.org/downloads/>.
Use a **mesma versão** nas três máquinas.
Na primeira tela do instalador, marque **"Add python.exe to PATH"**.

### 2.5 VS Code
Você já usa. Instale a extensão **Python** (Microsoft). A extensão **C/C++** é opcional
(só para colorir o código C++ se você quiser lê-lo).

### 2.6 PresentMon (recomendado)

A engine só conta os frames que ela mesma **renderiza**. Os frames criados pelo Frame
Generation não passam por ela. Para medir os frames **exibidos** na tela (com FG), é
preciso o PresentMon, ferramenta gratuita da Intel que funciona com qualquer GPU:

1. Baixe o executável `PresentMon-2.x.x-x64.exe` em <https://github.com/GameTechDev/PresentMon/releases>
2. Crie a pasta `C:\Tools\PresentMon\`, coloque o arquivo lá e renomeie para `PresentMon.exe`.
3. Você vai ligá-lo no `bench.json` (seção 5). Ele exige o terminal aberto **como Administrador**.

---

## 3. Organizar as pastas e abrir no VS Code

Use caminhos **curtos e sem espaços ou acentos**. A Unreal cria subpastas muito profundas
e o Windows tem limite de tamanho de caminho.

1. Baixe o UE5-Benchmark: na página do GitHub, **Code → Download ZIP**.
   Extraia para `C:\UE5Benchmark` (deve existir `C:\UE5Benchmark\Benchmark.uproject`).
2. Extraia este projeto para `C:\dlss-gpu-bench`.
3. No VS Code: **File → Open Folder** → `C:\dlss-gpu-bench`.
4. Abra o terminal do VS Code: **Terminal → New Terminal** (ou `` Ctrl+` ``).
   Todos os comandos deste guia são digitados nesse terminal.

---

## 4. Preparar o Python

No terminal do VS Code:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- O primeiro comando cria um ambiente isolado (`.venv`) só para este projeto.
- O segundo o ativa; o terminal passa a mostrar `(.venv)` no começo da linha.
  **Repita esse comando toda vez que abrir um terminal novo.**
- O terceiro instala as bibliotecas (psutil, nvidia-ml-py, pandas, matplotlib).

Se o PowerShell disser que a execução de scripts está desabilitada, rode uma vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Teste rodando `python run.py list`: deve aparecer a lista dos 7 testes.

---

## 5. Configurar os caminhos

Abra `config/bench.json` no VS Code. As linhas com `//` são explicações. Confira:

| Campo | O que colocar |
|---|---|
| `unreal.engine_dir` | Pasta da UE 5.4 (`C:/Program Files/Epic Games/UE_5.4`) |
| `unreal.project_dir` | `C:/UE5Benchmark` |
| `unreal.package_dir` | Onde o `.exe` será gerado (`C:/UE5BenchmarkBuild`) |
| `game.resolution` | Resolução dos testes, ex.: `[2560, 1440]` ou `[1920, 1080]` |
| `run.default_hours` | `48` |
| `run.sample_interval_s` | `5` (uma linha de dados a cada 5 s) |
| `run.output_dir` | Onde os resultados ficam (`C:/BenchmarkRuns`) |
| `presentmon.enabled` | `true` se você instalou o PresentMon |
| `monitor.external_cmd` | Opcional: seu próprio script de monitoramento, para rodar junto |

Use barras normais (`/`) nos caminhos.

Depois rode:

```powershell
python run.py check
```

Ele confere Python, bibliotecas, GPU, Unreal e caminhos, e diz o que falta. Neste ponto é
normal ele reclamar do plugin DLSS, do DX12 e do código C++; isso é resolvido nas próximas
seções.

---

## 6. Abrir o projeto Unreal pela primeira vez

Este passo confirma que a instalação está funcionando antes de mexer em qualquer coisa.

1. Dê duplo clique em `C:\UE5Benchmark\Benchmark.uproject`.
2. Vai aparecer: *"The following modules are missing or built with a different engine
   version... Would you like to rebuild them now?"* → clique em **Yes**.
   Isso compila o C++ do projeto com o Build Tools. Leva alguns minutos.
   - Se der erro aqui, o problema é a instalação do Build Tools (seção 2.3).
3. Na primeira abertura a Unreal compila milhares de **shaders** (contador no canto inferior
   direito). Pode levar de 10 a 40 minutos. Espere terminar.
4. Clique em **Play** (▶ na barra de cima). A câmera deve percorrer a cena e, ao fim do
   percurso, a tela escurece. Esse é o comportamento original que vamos trocar.
5. Aperte `Esc` e **feche o Editor**.

---

## 7. Instalar o plugin DLSS

Sem o plugin, as configurações de DLSS não existem no jogo.

> A página principal da NVIDIA só oferece o plugin para UE 5.5 a 5.8. A versão para 5.4
> está no [arquivo oficial de versões anteriores](https://forums.developer.nvidia.com/t/nvidia-dlss-unreal-engine-plugin-archive/377564).
> Este projeto foi validado com o **DLSS 4.5 Plugin v8.6.1** (21/05/2026), o mais recente
> para UE 5.4. Use a mesma versão em todas as máquinas e cite-a no trabalho.

1. Crie uma conta gratuita em <https://developer.nvidia.com> e, logado, baixe:
   <https://developer.nvidia.com/downloads/assets/gameworks/downloads/secure/dlss/ue-dlss-5.4/8.6.1/2026.05.21_ue5.4_dlss4.5plugin_v8.6.1.zip>
2. Extraia o zip. Dentro há uma pasta `Plugins` com as subpastas `DLSS`,
   `DLSSMoviePipelineSupport`, `NIS`, `Streamline`, `StreamlineCore`, `StreamlineDeepDVC`,
   `StreamlineDLSSG`, `StreamlineNGXCommon` e `StreamlineReflex`.
3. Copie **todas essas subpastas** para `C:\UE5Benchmark\Plugins\`. Deve ficar, por exemplo,
   `C:\UE5Benchmark\Plugins\DLSS\DLSS.uplugin`. A pasta `ProjectCleaner` que já está lá pode ficar.

Não é preciso habilitar os plugins na mão: o `python run.py apply` (seção 8) habilita no
`Benchmark.uproject` os quatro que o benchmark usa: `DLSS`, `StreamlineCore`,
`StreamlineDLSSG` e `StreamlineReflex`.

**Antes dos testes, em todas as máquinas:**
- **NVIDIA App:** desligue qualquer *override* de DLSS (modelo/preset, modo do Frame
  Generation). Senão o driver pode trocar o modelo do DLSS por conta própria e as máquinas
  deixam de ser comparáveis.
- **Windows → Configurações → Sistema → Tela → Elementos gráficos:** ligue o
  **Agendamento de GPU acelerado por hardware**. O Frame Generation exige.

---

## 8. Aplicar o código do benchmark e compilar

Com o **Editor fechado**, no terminal do VS Code:

```powershell
python run.py apply
python run.py build
```

**`apply`** faz quatro coisas:
- copia os arquivos de `unreal/Source/Benchmark/` para `C:\UE5Benchmark\Source\Benchmark\`;
- habilita no `Benchmark.uproject` os plugins da NVIDIA que o código usa (e se recusa a
  continuar se eles não estiverem em `C:\UE5Benchmark\Plugins`);
- no `DefaultEngine.ini`, troca a API gráfica padrão de Vulkan para **DirectX 12**
  (o Frame Generation só funciona em DX12);
- liga o **ray tracing por hardware** (sem ele o Ray Reconstruction não tem o que fazer).
  Isso vale para **todos** os testes, para que sejam comparáveis entre si.

Os arquivos originais ficam guardados em `C:\UE5Benchmark\_bench_backup\<data>\`.

**`build`** compila o C++. Termina com algo como `Result: Succeeded`. Se aparecer
`Unable to build while Live Coding is active`, o Editor ainda está aberto: feche-o.

### O que mudou no comportamento do jogo

- A câmera **volta ao início do percurso** e continua indefinidamente (antes, parava).
- Recebe pela linha de comando: duração, nome do teste, pasta de saída e configurações de DLSS.
- Grava `engine_samples.csv` a cada 5 s: FPS médio, 1% low, tempo de frame, tempo de GPU etc.
- 3 s após abrir, grava `run_config.json` com o valor **real** de cada configuração de DLSS
  e com o **suporte de hardware** informado pelo próprio plugin da NVIDIA (DLSS-SR, DLSS-RR,
  Frame Generation) e o modo ativo (ex.: `DLAA`, `Quality`; FG `On2X`). Se um recurso que o
  teste usa não estiver disponível naquela GPU, o teste é abortado com o motivo.
- Com Frame Generation, grava também o **FPS exibido** (inclui os frames gerados), medido
  pelo plugin. Funciona no Windows e no Linux, sem depender do PresentMon.
- Fecha sozinho quando o tempo acaba.
- O HUD mostra o nome do teste, o tempo decorrido, a volta atual e o estado do DLSS.

### Testar no Editor (opcional)

Abra o projeto e aperte **Play**. Por padrão ele roda 5 min. No **Output Log**
(**Window → Output Log**) aparecem linhas `[Bench]`. Os arquivos ficam em
`C:\UE5Benchmark\Saved\BenchResults\editor\`. Na primeira abertura depois do `apply`, a
Unreal recompila os shaders por causa do ray tracing; espere terminar antes.

---

## 9. Empacotar o jogo

Rodar 48 h dentro do Editor não é confiável. O teste usa o jogo empacotado (`.exe`):

```powershell
python run.py package
```

Leva de 20 minutos a mais de uma hora (cozinha todos os assets e compila shaders).
Termina com `BUILD SUCCESSFUL`. O executável fica em
`C:\UE5BenchmarkBuild\Windows\Benchmark\Binaries\Win64\Benchmark.exe`.

> Sempre que alterar código C++ ou ligar/desligar plugins, rode `build` e `package` de novo.
> Mudanças em `config/tests.json` **não** exigem reempacotar.

Rode `python run.py check` de novo: agora deve estar tudo `[OK]`.

---

## 10. Validação rápida (antes das 48 h)

**Não pule este passo.** Ele roda os 7 testes por 3 minutos cada (~30 min no total):

```powershell
python run.py run --tests all --minutes 3
```

O programa mostra o plano e pede confirmação. Para cada teste ele:
1. abre o jogo em tela cheia;
2. lê o `run_config.json` e confere se **cada** configuração ficou com o valor pedido;
3. se algo não bateu, **aborta aquele teste** e diz qual configuração falhou;
4. ao final, gera os gráficos.

Confira no terminal que todos terminaram como `completed`. Se algum terminar como
`aborted_cvar_check`, veja a seção 15.

Confira também **visualmente**:
- No teste 5 (Super Resolution), a imagem fica levemente diferente e o FPS sobe.
- No teste 3 (Frame Generation), com o PresentMon ligado, o "FPS exibido" no gráfico fica
  bem acima do FPS renderizado. Frame Generation exige **RTX série 40 ou mais nova**.

---

## 11. Rodar a bateria de verdade

> 7 testes × 48 h = **14 dias** de execução contínua, mais as pausas entre testes.

Você pode rodar tudo de uma vez:

```powershell
python run.py run --tests all --hours 48
```

Ou um teste (ou grupo) por vez, o que permite usar o computador entre um e outro:

```powershell
python run.py run --tests 1 --hours 48
python run.py run --tests 2 --hours 48
...
```

Cada execução cria uma pasta `C:\BenchmarkRuns\sessao_<data>_<hora>\`. Para comparar
testes que rodaram em sessões diferentes, gere um relatório combinado:

```powershell
python run.py report --all-sessions
python run.py report C:/BenchmarkRuns/sessao_A C:/BenchmarkRuns/sessao_B
```

### Durante o teste
- O Windows é impedido de suspender ou desligar a tela enquanto o teste roda.
- Se o jogo fechar sozinho (crash), ele é reaberto automaticamente com o tempo que falta,
  e o evento fica registrado em `events.csv`.
- `Ctrl+C` no terminal interrompe tudo; os dados já gravados são mantidos.
- Para acompanhar de longe: o HUD do jogo mostra o tempo decorrido, e o `orquestrador.log`
  na pasta da sessão é atualizado em tempo real.

---

## 12. Arquivos de resultado

```
C:\BenchmarkRuns\sessao_2026-10-20_14-00-00\
├── orquestrador.log          ← tudo que aconteceu
├── bench.json, tests.json    ← cópia da configuração usada (reprodutibilidade)
├── resumo.csv                ← uma linha por teste com as médias
├── comparacao.png            ← FPS, potência, temperatura e FPS/W por teste
├── fps_distribuicao.png      ← distribuição do FPS de cada teste
├── fps_ao_longo_do_tempo.png ← todos os testes sobrepostos (tendência ao longo das horas)
└── 03_dlss_fg\
    ├── engine_samples.csv    ← do jogo, a cada 5 s
    ├── system_samples.csv    ← da GPU/CPU, a cada 5 s
    ├── run_config.json       ← valores reais das configurações de DLSS
    ├── events.csv            ← aberturas, conferências, crashes
    ├── summary.json          ← resumo do teste
    ├── grafico_teste.png     ← FPS, temperatura, potência e clock ao longo do tempo
    ├── unreal_01.log         ← log da Unreal
    └── presentmon\pm_*.csv   ← janelas do PresentMon (se ligado)
```

### `engine_samples.csv` (medido pelo jogo)

| Coluna | Significado |
|---|---|
| `avg_fps` | FPS médio renderizado na janela de 5 s |
| `low1_fps` | "1% low": FPS no pior 1% dos frames da janela |
| `avg_frametime_ms`, `p99_frametime_ms`, `max_frametime_ms` | Tempo de frame médio, percentil 99 e máximo |
| `gpu_time_ms` | Tempo que a GPU levou no último frame, medido pela engine |
| `game_thread_ms`, `render_thread_ms` | Tempo das threads de CPU (indica gargalo de CPU) |
| `dlssg_fps` | FPS **exibido** com Frame Generation (frames renderizados + gerados); 0 sem FG |
| `dlssg_frames_presented` | Frames exibidos por frame renderizado (ex.: 2 no modo 2x) |
| `lap` | Volta atual no percurso da câmera |

### `system_samples.csv` (medido pelo Python, via NVML)

Uso da GPU e da VRAM, temperatura, potência e limite de potência, energia acumulada,
clocks (gráfico, SM, memória), ventoinha, estado de energia (P-state), **motivos de
limitação de clock** (`sw_power_cap` = limitada por potência, `hw_thermal`/`sw_thermal` =
por temperatura), tráfego PCIe e uso de CPU/RAM.

---

## 13. Cuidados de metodologia

Para que a comparação entre os testes seja válida:

- **Mesmas condições em todos:** mesma resolução, mesmo driver, mesmo build do jogo, mesma
  posição do PC e, se possível, mesma temperatura ambiente (anote-a).
- **Pausa entre testes:** `cooldown_minutes` (padrão 10) deixa a GPU esfriar, para um teste
  não começar já aquecido pelo anterior.
- **Aquecimento descartado:** os primeiros `warmup_minutes` (padrão 5) ficam fora das
  estatísticas (faixa cinza nos gráficos), porque incluem compilação de shaders e a GPU
  ainda está esquentando.
- **V-Sync e limite de FPS desligados** em todos os testes, para a GPU trabalhar no máximo.
  No Painel de Controle NVIDIA, deixe "Sincronização vertical" como "Usar configuração do
  aplicativo" e sem limite de FPS global.
- **Windows:** plano de energia "Alto desempenho", atualizações pausadas, nenhum outro
  programa pesado aberto, notificações desligadas.
- **FPS com Frame Generation:** compare os testes com FG pelo **FPS exibido** (coluna
  `dlssg_fps`, ou o PresentMon no Windows); o FPS da engine conta só os frames renderizados.
- **Modo do Frame Generation fixo:** `r.Streamline.DLSSG.FramesToGenerate = 1` (2x) em todos
  os testes com FG. A RTX 50 aceita 3x e 4x; se for usar, mude em `tests.json` e mantenha igual
  em todas as máquinas.
- **Ray Reconstruction:** o teste de RR desliga os denoisers da própria Unreal que a RR
  substitui (sombras e reflexos do Lumen), como faz a função oficial do plugin.
- **Registre tudo:** a pasta da sessão guarda a configuração exata; anote também modelo da
  GPU, driver e temperatura ambiente no seu trabalho.

---

## 14. Alterar os testes

Tudo está em `config/tests.json`. Cada teste é montado assim:
`base_cvars` + `all_off` + as features do teste, na ordem listada.

Exemplos:

**Super Resolution no modo Performance em vez de Quality:**
```json
"sr": { "r.ScreenPercentage": "50" }
```
(66.7 = Quality, 58 = Balanced, 50 = Performance, 33.3 = Ultra Performance)

**Adicionar um teste 8 com as três features:**
```json
{ "id": 8, "name": "08_dlss_fg_rr_sr", "features": ["dlss", "fg", "rr", "sr"] }
```

Depois de editar, rode `python run.py list` para conferir as configurações finais de cada
teste. Não precisa recompilar nem reempacotar.

---

## 15. Solução de problemas

| Problema | Causa provável e solução |
|---|---|
| `cvar ... nao existe no jogo` | O plugin correspondente não está habilitado (seção 7), ou o nome mudou na sua versão do plugin. Rode o jogo, abra o console (tecla `'` ou `~`), digite o início do nome (`r.NGX`, `r.Streamline`) e veja as opções; corrija em `tests.json`. Se for `t.IdleWhenNotForeground`, pode removê-lo de `base_cvars`. |
| `Frame Generation nao esta disponivel nesta maquina: ...` | O texto depois dos dois-pontos é o motivo informado pela NVIDIA. `NotSupportedIncompatibleHardware`: GPU anterior à RTX 40. `NotSupportedHardewareSchedulingDisabled`: ligue o "Agendamento de GPU acelerado por hardware" (seção 7). `NotSupportedDriverOutOfDate`: atualize o driver. |
| `run_config.json sem o bloco 'support'` | O jogo empacotado é de uma versão antiga do código: rode `apply`, `build` e `package` de novo. |
| `O jogo nao gravou o run_config.json` | Na primeira abertura a compilação de shaders pode demorar; aumente `startup_timeout_s`. Veja também o `unreal_01.log` na pasta do teste. |
| Erro no `build` | Copie o trecho com `error` do terminal. Os mais comuns: Editor aberto (Live Coding), Build Tools sem o MSVC/Windows SDK, ou versão do compilador (seção 2.3). |
| `run.py check` não encontra a GPU | Atualize o driver NVIDIA e rode `pip install nvidia-ml-py` com o `.venv` ativo. |
| PresentMon não grava nada | Abra o VS Code (ou o terminal) **como Administrador**. Se a sua versão usar outros nomes de parâmetros, ajuste `presentmon.args` no `bench.json`. |
| Tela preta ou câmera parada | O nível precisa ter o `MyCameraActor` com `SplineActor` e `BenchmarkMgr` preenchidos (já vem assim no projeto original). Veja o `unreal_01.log`. |
| Quero voltar ao projeto original | Copie os arquivos de `C:\UE5Benchmark\_bench_backup\<data>\` de volta para `Source\Benchmark\` e `Config\`. |

### Editar o C++ no VS Code (opcional)

Se quiser ler ou alterar o C++ com autocompletar: no Editor da Unreal, **Edit → Editor
Preferences → Source Code → Source Code Editor = Visual Studio Code**, depois
**Tools → Refresh Visual Studio Code Project**. Isso cria `Benchmark.code-workspace` em
`C:\UE5Benchmark`; abra esse arquivo no VS Code. Edite sempre os arquivos em
`dlss-gpu-bench/unreal/` e rode `apply` + `build`, para manter este projeto como a fonte
da verdade.

---

## 16. Análise de software aging (Mann-Kendall)

O `mann_kendall.py` roda **depois** dos testes. Ele só lê as pastas de resultado e grava a
análise numa pasta nova; não altera nada do que foi coletado. Também não depende da Unreal
nem da GPU, então pode rodar em qualquer computador que tenha o Python e as pastas.

### O que ele faz

Para cada teste e cada métrica:

1. **Descarta o aquecimento** (padrão: 30 min) no início de cada trecho, porque a
   alocação inicial de memória e a compilação de shaders criam uma subida que não é
   envelhecimento.
2. **Separa os trechos** quando o jogo foi reiniciado no meio do teste. Um reinício zera o
   estado do processo (funciona como um "rejuvenescimento" do software), então cada trecho é analisado separadamente
   além do teste completo.
3. **Agrega** em médias por janela (padrão: 5 min, ou seja, 576 pontos em 48 h).
4. Aplica o **teste de Mann-Kendall** em duas versões:
   - **original** (Mann, 1945; Kendall, 1975);
   - **com correção de Hamed-Rao** (Hamed & Rao, 1998), que corrige a variância para
     autocorrelação. É a versão que decide, por padrão.
5. Calcula a **inclinação de Sen** (Sen, 1968) em unidades por hora, com intervalo de
   confiança (Gilbert, 1987), e a variação total estimada no período.
6. Para cada métrica, diz se a tendência encontrada vai na direção do envelhecimento
   (memória e tempo de frame subindo, FPS caindo).

### Como rodar

Copie as pastas de resultado do Windows e do Linux para o mesmo computador e rode:

```powershell
python mann_kendall.py --sessao windows=C:/BenchmarkRuns --sessao linux=D:/resultados_linux
```

O texto antes do `=` é o rótulo que aparece nas tabelas. Cada `--sessao` pode ser a pasta
de um teste, de uma sessão ou uma pasta com várias sessões (ex.: um teste de 48 h por
sessão).

Outros exemplos:

```powershell
# Só uma plataforma
python mann_kendall.py --sessao windows=C:/BenchmarkRuns/sessao_2026-10-20_14-00-00

# Só algumas métricas
python mann_kendall.py --sessao windows=C:/BenchmarkRuns --metricas process_mem_mb,avg_frametime_ms

# Um CSV qualquer (por exemplo, o do seu próprio script de monitoramento)
python mann_kendall.py --csv meu_monitor.csv --coluna-tempo timestamp --colunas ram_mb,vram_mb

# Validação rápida (testes de 3 min): sem aquecimento e janela curta
python mann_kendall.py --sessao teste=C:/BenchmarkRuns --aquecimento 0 --janela 5s
```

| Opção | Padrão | Significado |
|---|---|---|
| `--janela` | `5min` | Média por janela antes do teste (`1min`, `15min`, `1h`…). `0` = sem agregação |
| `--aquecimento` | `30` | Minutos descartados no início de cada trecho |
| `--alfa` | `0.05` | Nível de significância |
| `--metodo` | `hamed_rao` | Qual versão decide (`hamed_rao` ou `original`); as duas são sempre calculadas |
| `--max-lag` | todos | Maior lag usado na correção de Hamed-Rao |
| `--metricas` | todas | Lista separada por vírgula |
| `--saida` | `analises/mann_kendall_<data>` | Pasta de saída |

### Arquivos gerados

```
analises/mann_kendall_2026-11-05_10-00-00/
├── mann_kendall_resultados.csv   ← uma linha por rótulo × teste × trecho × métrica
├── comparacao_entre_rotulos.csv  ← Windows e Linux lado a lado (quando há 2+ rótulos)
├── parametros.json               ← parâmetros usados (para citar no trabalho)
└── graficos/<rotulo>__<sessao>__<teste>.png ← série agregada + reta de Sen
```

Colunas principais de `mann_kendall_resultados.csv`:

| Coluna | Significado |
|---|---|
| `trecho` | `completo` ou `trecho N` (quando houve reinício) |
| `n` | Número de pontos analisados (após aquecimento e agregação) |
| `S`, `tau` | Estatística S e tau de Kendall |
| `z_original`, `p_original`, `tendencia_original` | Mann-Kendall original |
| `z_hamed_rao`, `p_hamed_rao`, `tendencia_hamed_rao` | Com correção de autocorrelação |
| `fator_hamed_rao` | n/n\*: quanto a autocorrelação inflou a variância (1 = nenhuma) |
| `tendencia_decisao` | Resultado da versão escolhida em `--metodo` |
| `sen_por_hora`, `sen_ic_inferior`, `sen_ic_superior` | Inclinação de Sen e IC |
| `variacao_total`, `variacao_pct` | Variação estimada no período analisado |
| `sinal_de_envelhecimento` | `sim`, `nao`, `nao (melhora)`, `contexto` ou `dados insuficientes` |

Métricas analisadas:

| Métrica | Envelhecimento se… |
|---|---|
| `process_mem_mb` (memória do processo do jogo) | sobe |
| `vram_used_mb`, `ram_used_mb` | sobe |
| `avg_frametime_ms`, `p99_frametime_ms`, `gpu_time_ms`, `game_thread_ms`, `render_thread_ms` | sobe |
| `avg_fps`, `low1_fps`, `dlssg_fps` (FPS exibido, só nos testes com FG) | cai |
| `gpu_temp_c`, `clock_sm_mhz`, `power_w`, `gpu_util_pct`, `cpu_util_pct` | **contexto**: explicam a causa, não são envelhecimento |

### Como interpretar (pontos para a metodologia)

1. **p < α indica tendência monotônica**, não a sua causa. É a evidência estatística; o
   texto do trabalho é que conecta isso a software aging.
2. **Olhe o tamanho, não só o p-valor.** Com 48 h de dados, tendências minúsculas ficam
   "significativas". Por isso a tabela traz a inclinação de Sen e a variação percentual.
   Vale definir com o seu orientador um limiar prático (ex.: só considerar envelhecimento
   relevante se a variação passar de X% em 48 h).
3. **Separe envelhecimento de efeito térmico.** Se o FPS cai mas o clock SM também cai e a
   temperatura sobe, a causa provável é a GPU limitando a si mesma, não o software. O
   resumo no terminal avisa quando isso acontece.
4. **Reinícios:** um crash no meio do teste zera a memória. Nesse caso o resultado de cada
   `trecho` é o mais confiável; o `completo` mistura os dois lados do salto.
5. **Por que Hamed-Rao por padrão:** amostras de 5 s são fortemente autocorrelacionadas, e
   o Mann-Kendall original assume independência. Em dados simulados sem tendência, o tempo
   de frame bruto deu p = 0,00005 no teste original (falso positivo) e p = 0,16 com a
   correção. As duas versões ficam na tabela, então você pode reportar ambas.
6. **Muitas comparações:** são várias métricas × 7 testes × 2 plataformas. Com α = 0,05,
   espera-se ~5% de falsos positivos só por acaso. Se for relevante para o trabalho,
   aplique uma correção (ex.: Bonferroni, `--alfa 0.05/N`) ou declare a limitação.
7. **Windows × Linux:** no Linux todo frame passa pela tradução do Proton, então compare a
   **existência e o tamanho das tendências** entre plataformas, não os valores absolutos.

### Validação da implementação

O teste foi implementado em `bench/mk_stats.py` (só numpy), para aguentar séries de 48 h
inteiras sem estourar a memória. Ele foi conferido contra o pacote **pyMannKendall**
(Hussain & Mahmud, 2019), a implementação de referência em Python: 36 de 36 casos
idênticos (S, variância, Z, p, Hamed-Rao, inclinação e intercepto de Sen), com séries
com e sem tendência, com autocorrelação e com empates. Para repetir:

```powershell
pip install pymannkendall
python tests/validar_mann_kendall.py
```

Diferenças em relação ao pyMannKendall: os p-valores muito pequenos são calculados com
`erfc` (o pyMannKendall arredonda para 0 abaixo de ~1e-16), e com mais de 3.000 pontos a
inclinação de Sen é estimada com uma amostra de 4 milhões de pares (semente fixa), em vez
de todos os pares. Com a janela padrão de 5 min, um teste de 48 h tem ~570 pontos e o
cálculo é exato.

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