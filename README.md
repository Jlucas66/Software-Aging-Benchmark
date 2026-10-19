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
├── requirements.txt        ← bibliotecas Python
├── config/
│   ├── bench.json          ← caminhos, resolução, duração, intervalo de amostragem
│   └── tests.json          ← os 7 testes e as configurações de DLSS de cada um
├── bench/                  ← código Python do orquestrador
│   ├── config.py, runner.py, monitor.py, presentmon.py, report.py, ue_build.py
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
compilador da Microsoft (MSVC). Você não precisa usar a IDE Visual Studio, só instalar as
ferramentas de compilação:

1. Baixe o **Build Tools para Visual Studio 2022**:
   <https://visualstudio.microsoft.com/visual-cpp-build-tools/>
2. No instalador, marque a carga de trabalho **"Desenvolvimento para desktop com C++"**.
3. No painel da direita, confirme que estão marcados:
   - **MSVC v143 - VS 2022 C++ x64/x86 build tools**
   - **Windows 11 SDK** (qualquer versão recente)
4. Instale (~8 GB) e **reinicie o computador**.

> Se mais tarde a compilação reclamar da versão do compilador, abra o instalador de novo,
> vá em **Componentes individuais** e marque a versão do MSVC que a mensagem pedir
> (a UE 5.4 prefere a **14.38**).

### 2.4 Python
Instale o Python **3.11 ou 3.12** em <https://www.python.org/downloads/>.
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

1. Acesse <https://developer.nvidia.com/rtx/dlss/get-started>, crie uma conta NVIDIA
   Developer (gratuita) e baixe o **DLSS Plugin para Unreal Engine 5.4**.
2. Dentro do zip há uma pasta `Plugins` com subpastas (`DLSS`, `Streamline...`, `NIS`, etc.).
3. Crie a pasta `C:\UE5Benchmark\Plugins` e copie **para dentro dela** todas essas subpastas.
   Deve ficar, por exemplo: `C:\UE5Benchmark\Plugins\DLSS\DLSS.uplugin`.
4. Abra `Benchmark.uproject`. Se perguntar sobre módulos para recompilar, clique em **Yes**.
5. No Editor: **Edit → Plugins**, busque **"DLSS"** e **"Streamline"** e marque todos os
   relacionados a Super Resolution/DLAA, Ray Reconstruction, Frame Generation e Reflex.
   (O NIS é opcional.) Clique em **Restart Now**.
6. Feche o Editor.

---

## 8. Aplicar o código do benchmark e compilar

Com o **Editor fechado**, no terminal do VS Code:

```powershell
python run.py apply
python run.py build
```

**`apply`** faz três coisas:
- copia os arquivos de `unreal/Source/Benchmark/` para `C:\UE5Benchmark\Source\Benchmark\`;
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
- 3 s após abrir, grava `run_config.json` com o valor **real** de cada configuração de DLSS.
- Fecha sozinho quando o tempo acaba.
- O HUD mostra o nome do teste, o tempo decorrido e a volta atual.

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
- **FPS com Frame Generation:** compare os testes com FG pelo **FPS exibido** (PresentMon);
  o FPS da engine conta só os frames renderizados.
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
| `pedido=1 atual=0` em `r.Streamline.DLSSG.Enable` | GPU sem suporte a Frame Generation (precisa de RTX 40+), jogo não está em DX12, ou "Hardware-accelerated GPU scheduling" desligado no Windows (Configurações → Sistema → Tela → Elementos gráficos). |
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
