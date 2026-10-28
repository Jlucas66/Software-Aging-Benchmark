# Rodar o benchmark em outra máquina

Guia para preparar uma máquina nova (ex.: o computador do laboratório) e rodar os testes,
no **Windows 11** e no **Linux** (dual boot na mesma máquina).

## Sumário

1. [O que a máquina precisa](#1-o-que-a-máquina-precisa)
2. [Windows 11](#2-windows-11)
3. [Linux (Proton)](#3-linux-proton)
4. [Antes de cada teste longo](#4-antes-de-cada-teste-longo)
5. [Depois dos testes: juntar os resultados](#5-depois-dos-testes-juntar-os-resultados)
6. [Ficha da máquina](#6-ficha-da-máquina)
7. [Problemas comuns](#7-problemas-comuns)

---

## 1. O que a máquina precisa

| O quê | O que é | Como conseguir |
|---|---|---|
| **O projeto** | Código Python, configurações e resultados (poucos MB) | `git clone` do GitHub |
| **O jogo pronto** (`UE5BenchmarkBuild`) | O `Benchmark.exe` com o mapa, os shaders e o DLSS dentro (~2,4 GB) | **Caminho A** ou **Caminho B** (abaixo) |

**Caminho A: compilar na própria máquina (Windows).** Não depende de nenhuma outra
máquina. Exige instalar a Unreal Engine e o compilador: são cerca de 50 GB de download,
uns 150 GB livres em disco, permissão de administrador e de 3 a 5 horas no total (a maior
parte é download e o empacotamento, que roda sozinho).

**Caminho B: baixar o jogo pronto do GitHub.** Rápido (só o download de ~2,4 GB), mas
alguém precisa antes enviar o jogo para o GitHub a partir de uma máquina que já o tenha
(seção 2.3, Caminho B).

**No Linux não dá para compilar** (o jogo é de Windows e roda pelo Proton). O Linux pega o
jogo da partição do Windows da mesma máquina (dual boot) ou baixa do GitHub (Caminho B).

> **Uma build oficial para tudo.** Todos os testes que vão ser comparados entre si devem
> usar o **mesmo** `Benchmark.exe`. Se você compilar no laboratório, use essa build no
> Windows e no Linux do laboratório, e de preferência envie-a para o GitHub (Caminho B)
> para que ela seja a build de todas as máquinas daqui para frente. Anote na ficha (seção 6)
> de onde veio a build usada em cada teste.

---

## 2. Windows 11

### 2.1 Programas básicos

| Programa | Observação |
|---|---|
| **Driver da NVIDIA** | Pelo NVIDIA App ou <https://www.nvidia.com/drivers>. Anote a versão (ela também fica no `sessao.json`) |
| **Python 3.11 ou mais novo** | <https://www.python.org/downloads/>. Na primeira tela do instalador, marque **"Add python.exe to PATH"** |
| **Git** | <https://git-scm.com/download/win> |
| **7-Zip** (só no Caminho B) | <https://www.7-zip.org/> |

### 2.2 Baixar o projeto e preparar o Python

Use um caminho curto, sem espaços e fora do OneDrive:
```powershell
cd C:\
mkdir Pesquisa
cd Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Se o PowerShell bloquear o `activate`, rode uma vez
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo. O `activate` precisa
ser repetido em todo PowerShell novo (a linha passa a começar com `(.venv)`).

### 2.3 Conseguir o jogo

No fim, por qualquer caminho, tem que existir
`C:\UE5BenchmarkBuild\Windows\Benchmark\Binaries\Win64\Benchmark.exe`.

#### Caminho A: compilar nesta máquina

**A1. Unreal Engine 5.4.** Instale o Epic Games Launcher (<https://store.epicgames.com/download>),
entre com uma conta Epic (gratuita), vá em **Unreal Engine → Biblioteca → +** ao lado de
"Versões do motor", escolha **5.4** e clique em **Instalar** (~40 GB). Deixe na pasta padrão
`C:\Program Files\Epic Games\UE_5.4`.

**A2. Compilador (Build Tools 2022 com MSVC 14.38).** Baixe
<https://aka.ms/vs/17/release/vs_buildtools.exe> e, no PowerShell:
```powershell
cd $env:USERPROFILE\Downloads
.\vs_buildtools.exe --add Microsoft.VisualStudio.Workload.VCTools `
  --add Microsoft.VisualStudio.Component.VC.14.38.17.8.x86.x64 `
  --add Microsoft.VisualStudio.Component.Windows11SDK.22621 `
  --add Microsoft.Net.Component.4.8.SDK
```
Confira no instalador: **Build Tools 2022** (não 2026); **MSVC v143 (v14.38-17.8)**,
**SDK do Windows 11 (10.0.22621.0)** e **SDK do .NET Framework 4.8** marcados; **MSVC
(Mais recente)** desmarcado. Instale e **reinicie**.

Depois, em `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\`,
anote o nome da pasta que começa com `14.38.` e crie o arquivo
`%APPDATA%\Unreal Engine\UnrealBuildTool\BuildConfiguration.xml` (crie as pastas se não
existirem), trocando o número pelo que você anotou:
```xml
<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
  <WindowsPlatform>
    <CompilerVersion>14.38.33130</CompilerVersion>
  </WindowsPlatform>
</Configuration>
```

**A3. Pasta `Content` (mapas e texturas).** Na página do
[UE5-Benchmark original](https://github.com/flyingllama87/UE5-Benchmark), clique em
**Code → Download ZIP**. Do zip, copie **só a pasta `Content`** para
`C:\Pesquisa\Software-Aging-Benchmark\UE5Benchmark\`. Deve existir
`UE5Benchmark\Content\BenchmarkLevel.umap`. Não copie o resto do zip: o `Source`, o
`Config` e o `.uproject` do seu repositório já têm as modificações do benchmark.

**A4. Plugin DLSS 8.6.1.** Com uma conta gratuita em <https://developer.nvidia.com>, baixe
<https://developer.nvidia.com/downloads/assets/gameworks/downloads/secure/dlss/ue-dlss-5.4/8.6.1/2026.05.21_ue5.4_dlss4.5plugin_v8.6.1.zip>.
Copie **todas as subpastas** de `Plugins` do zip (`DLSS`, `NIS`, `Streamline*`…) para
`C:\Pesquisa\Software-Aging-Benchmark\UE5Benchmark\Plugins\`. Deve existir
`UE5Benchmark\Plugins\DLSS\DLSS.uplugin`. Use exatamente essa versão: é a mesma das outras
máquinas.

**A5. Compilar e empacotar.** Com o `.venv` ativo, na pasta do projeto:
```powershell
python run.py check
python run.py build
python run.py package
```
- O `check` deve mostrar Unreal, Content e plugins `[OK]` (o jogo ainda aparece como não
  encontrado, o que é normal antes do `package`).
- O `build` compila o C++ em poucos minutos e termina com `Result: Succeeded`.
- O `package` gera o jogo em `C:\UE5BenchmarkBuild`. Leva de 30 min a 2 h e passa um bom
  tempo parado na etapa de *cook* sem mostrar nada; é normal. Termina com `BUILD SUCCESSFUL`.

Erros comuns aqui estão na seção 7.

#### Caminho B: baixar o jogo pronto do GitHub

**B1. Enviar o jogo (uma vez só, na máquina que já tem o `C:\UE5BenchmarkBuild`).** O
GitHub aceita arquivos de até 2 GB em uma *release*, então o jogo vai dividido em partes.
Com o 7-Zip instalado:
```powershell
mkdir C:\Temp
& "C:\Program Files\7-Zip\7z.exe" a -v1900m C:\Temp\UE5BenchmarkBuild.7z C:\UE5BenchmarkBuild
```
Isso cria `UE5BenchmarkBuild.7z.001`, `.002`… em `C:\Temp`. Depois, no site do GitHub, no
seu repositório: **Releases → Draft a new release**, crie uma tag (ex.: `jogo-v1`), arraste
todas as partes para a área de anexos e clique em **Publish release**.

> O pacote contém o runtime do DLSS da NVIDIA e os assets do projeto original. Se o
> repositório for público, a release também será: prefira manter o repositório privado.

**B2. Baixar na máquina nova.** No GitHub, abra a release `jogo-v1`, baixe **todas** as
partes para a mesma pasta e extraia a partir da primeira (o 7-Zip junta as outras sozinho):
```powershell
& "C:\Program Files\7-Zip\7z.exe" x $env:USERPROFILE\Downloads\UE5BenchmarkBuild.7z.001 -oC:\
```
Confira se existe `C:\UE5BenchmarkBuild\Windows\Benchmark\Binaries\Win64\Benchmark.exe`.

### 2.4 Ajustar a configuração

Em `config/bench.json`, no bloco `"game"`, coloque a **resolução nativa do monitor desta
máquina** (ex.: `[1920, 1080]` ou `[2560, 1440]`). Use **a mesma resolução no Windows e no
Linux** dessa máquina. O resto fica como está.

### 2.5 Ajustes do Windows e da NVIDIA

| Onde | O que fazer | Por quê |
|---|---|---|
| Configurações → Sistema → Tela → Elementos gráficos | Ligar **Agendamento de GPU acelerado por hardware** e reiniciar | O Frame Generation exige |
| NVIDIA App | Desligar qualquer *override* de DLSS (modelo, preset, modo do FG), o **overlay** e o **Replay instantâneo** | Override troca o DLSS por conta própria; a gravação usa a GPU o tempo todo |
| Configurações → Jogos → Captura | Desligar a gravação em segundo plano (Xbox Game Bar) | Usa GPU e disco |
| Configurações → Windows Update | **Pausar** atualizações | Evita instalação e reinício no meio do teste |
| Segurança do Windows → Proteção contra vírus → Gerenciar configurações → Exclusões | Adicionar `C:\Pesquisa` e `C:\UE5BenchmarkBuild` | O antivírus não fica verificando os arquivos do teste |
| Gerenciador de Tarefas → Aplicativos de inicialização | Desabilitar tudo que não for essencial (Steam, Discord, OneDrive, navegador…) | Esses programas competem com o jogo |
| Painel de Controle → Opções de Energia | Plano **Alto desempenho**. Se houver Linux em dual boot, desligar a **Inicialização rápida** | Desempenho constante; sem a inicialização rápida, o Linux consegue abrir a partição do Windows |

No laboratório, combine com o responsável pela máquina antes de mexer no antivírus e nas
atualizações.

### 2.6 Validar (obrigatório antes de um teste longo)

```powershell
python run.py check
```
Python, GPU e o executável devem estar `[OK]`. Se você usou o Caminho B, os avisos `[..]`
sobre Unreal Engine, Content e Plugins são **normais** (eles só servem para compilar).

Se o jogo reclamar de uma DLL faltando ao abrir, rode uma vez o instalador que vem com ele:
`C:\UE5BenchmarkBuild\Windows\Engine\Extras\Redist\en-us\UEPrereqSetup_x64.exe`.

Teste curto de cada recurso (cerca de 1 h, contando as pausas):
```powershell
python run.py run --tests all --minutes 3
```
A primeira abertura compila shaders e pode demorar. No fim, todos devem estar `completo`.
Os testes 3 e 6 (Frame Generation) só passam em RTX 40 ou 50.

Abra o `sessao.json` da sessão criada em `BenchmarkRuns\` e confira em cada teste:
- `"status": "completo"`;
- `"ota_ativa": false` (as versões do DLSS estão travadas);
- `"ray_tracing": true`;
- `"dlss"`: `"Supported"` nos recursos que o teste usa.

**Evidência visual de que o DLSS está ativo (recomendado uma vez por máquina):** num
PowerShell **como Administrador**, ligue o indicador da NVIDIA, rode os testes curtos e
tire um print (`PrtSc`) de cada um; depois desligue:
```powershell
reg add "HKLM\SOFTWARE\NVIDIA Corporation\Global\NGXCore" /v ShowDlssIndicator /t REG_DWORD /d 1024 /f
python run.py run --tests 1,2,4,5 --minutes 3
reg add "HKLM\SOFTWARE\NVIDIA Corporation\Global\NGXCore" /v ShowDlssIndicator /t REG_DWORD /d 0 /f
```
No canto da tela aparecem a versão e o modo do DLSS e a resolução de entrada → saída. O
teste 1 não deve mostrar nada; o teste 2 deve mostrar entrada = saída (DLAA); o teste 5,
entrada menor que a saída (Super Resolution). Se o indicador não aparecer, troque `1024` por `1`.

---

## 3. Linux (Proton)

Testado no **Zorin OS 18** (baseado no Ubuntu 24.04). Em outras distribuições muda só a
forma de instalar o driver e os pacotes. No Linux roda o **mesmo `Benchmark.exe`** do
Windows, pelo Proton.

### 3.1 Driver da NVIDIA

Menu → **Drivers adicionais** → escolha o `nvidia-driver` mais novo marcado como
**proprietário, testado** → aplicar → reiniciar. Depois, no Terminal (Ctrl+Alt+T):
```bash
nvidia-smi
ls /usr/lib/x86_64-linux-gnu/nvidia/wine/
```
O primeiro mostra a placa e a versão do driver. O segundo deve listar `nvngx.dll`, sem a
qual o DLSS não funciona no Proton.

### 3.2 Pacotes

```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip p7zip-full
```

### 3.3 GE-Proton (versão fixa)

No navegador, abra <https://github.com/GloriousEggroll/proton-ge-custom/releases>, vá até
a **mesma versão usada nas outras máquinas** (ex.: `GE-Proton11-11`) e baixe o arquivo
`GE-ProtonXX-YY-x86_64.tar.gz` (não o `aarch64`). Depois:
```bash
mkdir -p ~/.local/share/Steam/compatibilitytools.d
tar -xf ~/Downloads/GE-Proton*-x86_64.tar.gz -C ~/.local/share/Steam/compatibilitytools.d/
ls ~/.local/share/Steam/compatibilitytools.d/
```
Anote o nome exato da pasta que aparecer. Se a pasta de downloads se chamar
`Transferências`, troque no comando.

### 3.4 umu-launcher

Em <https://github.com/Open-Wine-Components/umu-launcher/releases>, baixe o arquivo que
termina em **`-zipapp.tar`**. Depois:
```bash
tar -xf ~/Downloads/umu-launcher-*-zipapp.tar -C ~/.local/share/
ls ~/.local/share/umu/
```
Deve aparecer `umu-run`.

### 3.5 Conseguir o jogo

**Dual boot (o Windows da mesma máquina já tem o `C:\UE5BenchmarkBuild`):** abra o disco do
Windows no app Arquivos (para montar), veja o nome dele e copie:
```bash
ls /media/$USER/
rsync -a --info=progress2 "/media/$USER/NOME_DO_DISCO/UE5BenchmarkBuild" ~/
```
Se o disco não abrir ("hibernado" ou "somente leitura"), volte ao Windows, desligue a
**Inicialização rápida** (seção 2.5) e desligue o PC pelo menu Iniciar.

**Pelo GitHub (Caminho B):** baixe todas as partes da release `jogo-v1` e extraia:
```bash
7z x ~/Downloads/UE5BenchmarkBuild.7z.001 -o$HOME
```

Nos dois casos, confira:
```bash
ls ~/UE5BenchmarkBuild/Windows/Benchmark/Binaries/Win64/
```
Deve listar o `Benchmark.exe`.

### 3.6 Baixar o projeto e preparar o Python

```bash
mkdir -p ~/Pesquisa && cd ~/Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
O `source .venv/bin/activate` precisa ser repetido em todo terminal novo.

### 3.7 Ajustar a configuração

Em `config/bench.json`:
- bloco `"linux"`, campo `"proton_path"`: troque o nome da pasta pelo que apareceu no
  passo 3.3 (ex.: `~/.local/share/Steam/compatibilitytools.d/GE-Proton11-11`);
- bloco `"game"`, campo `"resolution"`: a mesma resolução usada no Windows dessa máquina.

### 3.8 Ajustes do Linux

- Configurações → Energia: **Tela em branco = Nunca** e **Suspensão automática** desligada.
- Desligue as atualizações automáticas (Atualizações de Software → Configurações) e feche
  os programas abertos.

### 3.9 Validar

```bash
python run.py check
```
Tudo deve estar `[OK]`, inclusive "Proton (Linux)" e a "Biblioteca do DLSS do driver".

```bash
python run.py run --tests 2 --minutes 3
```
**A primeira execução é só preparação:** o umu baixa o Steam Runtime (`steamrt4`),
cria o prefixo do Wine e compila os shaders. As mensagens `CRITICAL: steamrt4 validation
failed` nessa hora são normais. O teste pode terminar com poucas amostras ou como
`abortado (jogo nao iniciou)`. **Rode o mesmo comando de novo**: a segunda execução é a
validação de verdade. Depois rode os demais testes curtos (`--tests all --minutes 3`) e
confira o `sessao.json` como no Windows (seção 2.6). O bloco `"proton"` dele mostra a
versão do GE-Proton usada.

---

## 4. Antes de cada teste longo

Vale para Windows e Linux. É isso que torna os testes comparáveis entre si.

1. **Reinicie o computador.** Isso zera o estado do sistema operacional, que também
   envelhece; sem reiniciar, cada teste começaria de um estado diferente.
2. Entre no sistema e **espere 10–15 min sem mexer** (o sistema termina as tarefas de
   inicialização).
3. Confira que nenhum programa ficou aberto (navegador, Discord, Steam, VS Code…).
4. Anote a **hora de início** e a **temperatura ambiente** (seção 6).
5. Rode **um teste por vez**, num PowerShell/terminal avulso, fora do VS Code:
   ```
   python run.py run --tests 1 --hours 48
   ```
6. Deixe o **monitor ligado** durante todo o teste (pode baixar o brilho). Desligar o
   monitor pode tirar o jogo da tela cheia ou fechá-lo.

O programa já impede a suspensão, reabre o jogo se ele travar e grava os dados a cada 5 s
(uma interrupção só perde os últimos segundos).

---

## 5. Depois dos testes: juntar os resultados

Cada máquina cria pastas em `BenchmarkRuns/` com o nome terminando em `_windows` ou
`_linux`. Para analisar tudo junto, as pastas das duas plataformas precisam estar no mesmo
`BenchmarkRuns/`. A forma mais simples é pelo GitHub:

1. Na máquina onde o teste rodou: `git add -A`, `git commit -m "resultados teste N"` e
   `git push`.
2. Na máquina onde vai analisar: `git pull`.

(No Linux, o `git push` pede login no GitHub: use o seu usuário e um *Personal Access Token*
como senha, criado em GitHub → Settings → Developer settings → Personal access tokens. Em
dual boot, outra opção é copiar as pastas `_linux` para o projeto na partição do Windows e
fazer o push de lá.)

Análise (em qualquer máquina com o projeto):
```
python run.py report --all-sessions
python mann_kendall.py --aquecimento 120
```

---

## 6. Ficha da máquina

Boa parte destes dados o programa já grava sozinho no `sessao.json` de cada sessão
(sistema, CPU, RAM, GPU, driver, versões da Unreal, do plugin DLSS e do Proton). Anote à
mão o que ele não tem como saber:

| Item | Windows | Linux |
|---|---|---|
| Máquina / local | | |
| Monitor e resolução usada | | |
| Versão do driver NVIDIA | | |
| Origem da build do jogo (onde e quando foi compilada) | | |
| Versão do GE-Proton | — | |
| Temperatura ambiente no início de cada teste | | |
| Hora de início de cada teste | | |
| Programas desligados / exclusões do antivírus | | |
| Observações (quedas de energia, reinícios, uso da máquina por outras pessoas) | | |

---

## 7. Problemas comuns

| Problema | Solução |
|---|---|
| `Executavel do jogo nao encontrado` | O jogo não está em `C:\UE5BenchmarkBuild` (Windows) ou `~/UE5BenchmarkBuild` (Linux). Veja a seção 2.3 / 3.5 |
| `Pasta Content vazia ou ausente` / `Faltam plugins` | Caminho A, passos A3 e A4 |
| `has banned the MSVC 14.39` / `C4668 __has_feature` | Compilador errado: confira o `BuildConfiguration.xml` (passo A2) |
| `Could not find NetFxSDK install dir` | Falta o SDK do .NET Framework 4.8 (passo A2) |
| `Unable to build while Live Coding is active` | Feche o Editor da Unreal |
| Erro de caminho longo ao compilar | Use `C:\Pesquisa\...` e, se precisar, ative caminhos longos no Windows (`LongPathsEnabled`) |
| `No module named 'bench....'` | Algum arquivo `.py` ficou com nome errado ou fora da pasta `bench`. Os nomes são todos em minúsculas |
| Erro de sintaxe em `bench.json` | A mensagem mostra a linha: confira aspas, vírgulas e chaves |
| `Frame Generation nao esta disponivel nesta maquina: ...` | `NotSupportedIncompatibleHardware`: GPU anterior à RTX 40. `...HardwareSchedulingDisabled`: seção 2.5. `...DriverOutOfDate`: atualize o driver |
| `Atualizacao OTA da NVIDIA ainda ativa` | No NVIDIA App, desligue os overrides de DLSS e rode de novo |
| Linux: `Proton nao encontrado` | O nome da pasta em `"proton_path"` não bate com o da seção 3.3 |
| Linux: DLSS não suportado | Confira se `nvngx.dll` existe (seção 3.1) e se o bloco `"linux"` tem `"PROTON_ENABLE_NVAPI": "1"` |
| Linux: `O jogo nao gravou o run_config.json` na primeira vez | É a preparação do Proton (seção 3.9): rode de novo |
| `Nao consegui bloquear a suspensao automatica` | Desligue a suspensão nas configurações de energia do sistema |
| O teste ficou com status `rodando` no `sessao.json` | O computador desligou no meio (queda de energia, reinício). Os dados até ali estão no CSV; registre na ficha e refaça o teste |

Mais detalhes: `README.md` (funcionamento, resultados, Mann-Kendall) e `COMANDOS.md`
(lista rápida de comandos).
