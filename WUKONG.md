# Cena Black Myth: Wukong (Benchmark Tool)

Este guia roda a pesquisa (7 testes, duração configurável, uma linha de métricas a cada 5 s,
DLSS e features escolhidos antes de cada teste) no **Black Myth: Wukong Benchmark Tool**, o
benchmark gratuito da Game Science na Steam. O relatório e o Mann-Kendall são os mesmos do
UE5-Benchmark; muda só quem desenha a cena.

Tudo é feito pelo `wukong.py` (no lugar do `run.py`).

## Sumário

1. [Como funciona](#1-como-funciona)
2. [Instalar o Benchmark Tool](#2-instalar-o-benchmark-tool)
3. [Medição de FPS: Windows (PresentMon)](#3-medição-de-fps-windows-presentmon)
4. [Medição de FPS: Linux (MangoHud) e Proton](#4-medição-de-fps-linux-mangohud-e-proton)
5. [Modo de repetição (loop)](#5-modo-de-repetição-loop)
6. [Criar os perfis dos 7 testes](#6-criar-os-perfis-dos-7-testes)
7. [Validar](#7-validar)
8. [Quando o teste não começa sozinho: ações de teclado e mouse](#8-quando-o-teste-não-começa-sozinho-ações-de-teclado-e-mouse)
9. [Rodar a bateria](#9-rodar-a-bateria)
10. [Analisar](#10-analisar)
11. [Cuidados de metodologia](#11-cuidados-de-metodologia)
12. [Solução de problemas](#12-solução-de-problemas)

---

## 1. Como funciona

O Benchmark Tool **não tem linha de comando nem API**. O `wukong.py` usa o que existe:

| O que | Como |
|---|---|
| Configurações (DLSS, Frame Generation, ray tracing...) | Arquivo `b1/Saved/Config/Windows/GameUserSettings.ini` na pasta do jogo. Você configura **pelo menu do jogo** uma vez e salva como **perfil** de cada teste; antes de cada teste o perfil é copiado de volta |
| Abrir e começar | `steam -applaunch 3132990 -benchmark`. O `-benchmark` é um argumento da Unreal que, segundo quem já automatizou o tool, começa o teste direto sem menu. **Confirme na sua máquina** (passo 7) |
| Repetir por 48 h | Modo de repetição do próprio tool (passo 5). Se a volta acabar e o jogo parar, o orquestrador tenta começar outra volta (ações) e, em último caso, reabre o jogo |
| FPS a cada 5 s | PresentMon (Windows) ou MangoHud (Linux). O tool só informa FPS no fim de cada volta |
| FPS de cada volta | O tool grava um JSON por volta (`%TEMP%/b1/BenchMarkHistory/Tool`). O orquestrador copia para a sessão e monta `<teste>_voltas.csv` |
| Conferir se o DLSS ficou como pedido | O JSON da 1ª volta diz o que o jogo usou (`Dlss`, `InsertFrame`, `Rtx`, resolução). Diferença do perfil vira aviso no log e no `sessao.json` |
| Processo, memória, handles, GPU, outros processos, eventos do sistema | O mesmo monitor do UE5-Benchmark |

Detecção de estado, pela utilização da GPU: **rodando** = GPU ≥ 70 %; **volta acabou e parou**
= GPU < 40 % por 3 min (ajustável em `config/wukong.json`).

> **Por que o loop interno importa:** a pesquisa é de *software aging*. O que envelhece é o
> processo (memória, handles, fragmentação, estado do driver). Reabrir o jogo a cada volta de
> ~3 min zera isso. O `sessao.json` registra, por teste, quantas vezes o jogo foi aberto
> (`execucoes`) e quantas reaberturas foram por fim de volta (`reaberturas_fim_de_volta`).
> Num teste válido para aging, `execucoes` = 1.

## 2. Instalar o Benchmark Tool

1. Na Steam, procure **Black Myth: Wukong Benchmark Tool** (gratuito, ~8 GB) e instale.
2. Abra uma vez pela Steam. Aceite os termos, escolha idioma/brilho, **espere a compilação de
   shaders terminar** e saia pelo botão de sair do próprio tool.
3. No terminal, na pasta do repositório:
   ```powershell
   .venv\Scripts\activate          # Linux: source .venv/bin/activate
   python wukong.py check
   ```
   Ele acha a instalação sozinho pela Steam. Se não achar, preencha `wukong.install_dir` em
   `config/wukong.json`.
4. **NVIDIA App** (Windows): desligue os *overrides* de DLSS para este programa (mesmo motivo
   do UE5-Benchmark: a versão do DLSS tem que ser a que vem com o jogo, igual em todas as máquinas).

## 3. Medição de FPS: Windows (PresentMon)

1. Baixe o **PresentMon** (versão de console, `PresentMon-2.x.x-x64.exe`) em
   <https://github.com/GameTechDev/PresentMon/releases>.
2. Salve como `C:/Ferramentas/PresentMon/PresentMon.exe` (ou mude `frames.presentmon_exe`).
3. O PresentMon precisa de permissão para ler os eventos de vídeo: **rode o terminal como
   administrador**, ou coloque seu usuário no grupo **Performance Log Users**
   (`lusrmgr.msc` → Grupos) e saia/entre de novo no Windows.

Com a coluna `FrameType` (PresentMon 2.x), o CSV separa `fps` (frames **renderizados**) de
`fps_exibido` (renderizados + gerados pelo Frame Generation), igual ao UE5-Benchmark.

## 4. Medição de FPS: Linux (MangoHud) e Proton

O plugin e o jogo são Windows; no Linux roda pelo **Proton da própria Steam**.

1. Steam → botão direito no Benchmark Tool → **Propriedades → Compatibilidade** → marque
   *Forçar o uso de uma ferramenta de compatibilidade* e escolha **a mesma versão do Proton
   durante toda a pesquisa** (ex.: GE-Proton11-11, se ele estiver em
   `~/.local/share/Steam/compatibilitytools.d`). Anote a versão no trabalho.
2. Abra o tool uma vez pela Steam (cria o prefixo do Proton) e feche.
3. Instale MangoHud e xdotool: `sudo apt install mangohud xdotool` e crie a pasta
   `mkdir -p ~/wukong_mangohud`.
4. Em `config/wukong.json`: `"fonte": "mangohud"`.
5. Steam → Propriedades → **Opções de inicialização** (troque `SEU_USUARIO`):
   ```
   MANGOHUD_CONFIG="no_display,autostart_log=1,log_interval=1000,output_folder=/home/SEU_USUARIO/wukong_mangohud" mangohud %command%
   ```
   O `-benchmark` é acrescentado pelo orquestrador; não precisa colocar aqui.

> O MangoHud mede frames **apresentados**: com Frame Generation, o `fps` inclui os frames
> gerados (não dá para separar como no PresentMon). Para comparar Windows × Linux, use o FPS
> por volta do próprio tool (`<teste>_voltas.csv`), que é o mesmo instrumento nas duas plataformas.
> Os campos `CPUUsage`/`GPUUsage` do JSON do tool não funcionam no Proton (sempre 1 %) e não são usados.

## 5. Modo de repetição (loop)

O Benchmark Tool tem um modo de repetição para teste de carga. Descubra se ele fica salvo no
arquivo de configuração (assim ele entra nos perfis e funciona sozinho):

1. Abra o tool pela Steam, **sem mudar mais nada**, e saia. Rode:
   ```
   python wukong.py perfil salvar sem_loop
   ```
2. Abra de novo, **ligue o modo de repetição** (procure em Configurações ou na tela que aparece
   ao clicar em *Benchmark*) e saia pelo botão de sair.
3. Compare:
   ```
   python wukong.py perfil diff sem_loop atual
   ```
   - **Apareceu uma diferença** (uma chave do `UISettingData` ou uma linha nova): a opção fica
     salva. Ligue o loop antes de salvar **cada** perfil do passo 6 e pronto.
   - **Nenhuma diferença:** a opção não fica salva. Use as ações de teclado/mouse (passo 8) para
     ligar o loop (`acoes_inicio`) ou começar outra volta na tela de resultados (`acoes_nova_volta`).

O passo 7 confirma de verdade: várias voltas no mesmo processo = loop funcionando.

O mesmo `perfil diff` serve para descobrir qualquer opção do menu: mude **uma** coisa, saia e
compare.

## 6. Criar os perfis dos 7 testes

Para cada linha da tabela: abra o tool pela Steam → Configurações → ajuste → aplique →
**saia pelo botão de sair do tool** (ele só grava o arquivo ao sair) → rode o comando.

**Iguais em todos os testes** (anote os valores no trabalho):
- Resolução **1920×1080**, mesmo modo de tela em todos (o tool tem *janela sem borda* e *janela*)
- **Mesma predefinição de qualidade** (ex.: *Muito alto*) e o mesmo valor em cada item avançado
- Nível do **NVIDIA Full Ray Tracing** fixo (ex.: *Muito alto*) nos testes com RT
- VSync e limite de FPS **desligados** (o orquestrador também força isso por cima de todos os perfis)
- Modo de repetição ligado, se ele fica salvo (passo 5)

| Teste | Super Resolution Sampling | Resolução de amostragem | Frame Generation | Full Ray Tracing | Comando |
|---|---|---|---|---|---|
| 01_sem_dlss | **TSR** | 100 | desligado | desligado | `python wukong.py perfil salvar 01_sem_dlss` |
| 02_dlss | **DLSS** | 100 (= DLAA) | desligado | desligado | `python wukong.py perfil salvar 02_dlss` |
| 03_dlss_fg | DLSS | 100 | **ligado** | desligado | `python wukong.py perfil salvar 03_dlss_fg` |
| 04_dlss_rt | DLSS | 100 | desligado | **ligado** | `python wukong.py perfil salvar 04_dlss_rt` |
| 05_dlss_sr | DLSS | **66** (Qualidade) | desligado | desligado | `python wukong.py perfil salvar 05_dlss_sr` |
| 06_dlss_fg_rt | DLSS | 100 | **ligado** | **ligado** | `python wukong.py perfil salvar 06_dlss_fg_rt` |
| 07_dlss_rt_sr | DLSS | **66** | desligado | **ligado** | `python wukong.py perfil salvar 07_dlss_rt_sr` |

No tool a qualidade do DLSS é um controle deslizante: 90–100 = DLAA, 62–89 = Qualidade,
55–61 = Equilibrado, 40–54 = Desempenho, 25–39 = Ultra Desempenho.

> **Diferença para os testes do UE5-Benchmark:** o tool não tem Ray Reconstruction separado.
> Aqui a feature 2 é o *Full Ray Tracing*. Registre esse mapeamento no trabalho.

Depois: `python wukong.py check` deve mostrar os 7 perfis com os valores de `Dlss`,
`InsertFrame` e `Rtx` diferentes entre si, como na tabela. Use `perfil mostrar <nome> --tudo`
para ver tudo. Os perfis ficam em `config/wukong_perfis/` (vão para o Git, então a máquina do
laboratório usa exatamente os mesmos).

## 7. Validar

```
python wukong.py validar --tests 2 --minutes 12
```

Não mexa no computador durante o teste. No fim aparece um diagnóstico:

| Resultado | Significado |
|---|---|
| `Varias voltas no MESMO processo` | Tudo certo: começou sozinho e repete sozinho |
| `O teste nao comecou sozinho` | O `-benchmark` não funcionou: configure `acoes_inicio` (passo 8) |
| `parou N vez(es) no fim da volta e foi reaberto` | Loop desligado: passo 5 ou `acoes_nova_volta` |
| `O jogo usou: Dlss=... InsertFrame=...` | O que o jogo de fato aplicou, para conferir com o perfil |
| `Configuracao diferente do perfil` | O jogo ignorou alguma opção do perfil: salve o perfil de novo |
| `FPS medido a cada 5 s` | PresentMon/MangoHud funcionando |

Depois valide todos os testes rapidamente: `python wukong.py validar --tests all --minutes 8`.

## 8. Quando o teste não começa sozinho: ações de teclado e mouse

1. Abra o tool pela Steam e rode `python wukong.py calibrar`.
2. Coloque o mouse em cima de cada botão (ex.: *Benchmark*, *Confirmar*, o botão do loop, o de
   *testar de novo* na tela de resultados) e anote os dois números (frações da janela; valem em
   qualquer resolução).
3. Em `config/wukong.json`:
   ```jsonc
   "launch_args": [],
   "espera_menu_s": 40,
   "acoes_inicio": ["Key:Enter", "Wait:4000", "Click:0.115,0.452", "Wait:2500", "Click:0.393,0.580"],
   "acoes_nova_volta": ["Click:0.500,0.900"]
   ```
   Formatos: `Key:Enter` (também `Esc`, `Space`, `Tab`, setas, letras), `Click:x,y`, `Wait:ms`.
4. Valide de novo (passo 7). No Linux precisa de `xdotool` e sessão X11/XWayland.

## 9. Rodar a bateria

```
python wukong.py run --tests all --hours 48
```

Mesmo funcionamento do `run.py`: pausa de 10 min entre testes, sistema sem suspender, o
`sessao.json` regravado a cada mudança. No fim, o `GameUserSettings.ini` original do tool é
restaurado. Resultados em `BenchmarkRuns/wukong/<data>_<plataforma>/`:

| Arquivo | Conteúdo |
|---|---|
| `<teste>.csv` | Uma linha a cada 5 s (mesmas colunas do UE5-Benchmark) |
| `<teste>_voltas.csv` | Uma linha por volta: FPS médio/mín/máx/95 % do próprio tool, configurações usadas |
| `<teste>_voltas/` | JSON original de cada volta (com os quadros a cada ~0,3 s) |
| `<teste>_GameUserSettings.ini` | Configuração exata aplicada no teste |
| `<teste>_processos.csv`, `<teste>_eventos_sistema.txt` | Outros processos e eventos do sistema |
| `GameUserSettings.original.ini` | Backup do arquivo do tool antes da sessão |
| `sessao.json` | Máquina, versões (DLLs da NVIDIA do jogo, versão do jogo), aberturas, voltas, problemas |

## 10. Analisar

```
python wukong.py report
python mann_kendall.py --sessao BenchmarkRuns/wukong
```

Passe sempre a pasta `BenchmarkRuns/wukong` no Mann-Kendall: sem `--sessao`, ele lê todo o
`BenchmarkRuns/` e misturaria as sessões das duas cenas.

O `<teste>_voltas.csv` permite um segundo olhar de aging independente do PresentMon/MangoHud:
o FPS médio de cada volta ao longo das 48 h. Ele pode ir no Mann-Kendall com
`python mann_kendall.py --csv <sessao>/<teste>_voltas.csv --coluna-tempo TimeStamp --colunas FPSAvg,FPS95`
(`TimeStamp` está em segundos, que é o que o `--csv` espera).

## 11. Cuidados de metodologia

- **Cena fixa:** a câmera do tool é roteirizada, sem combate e sem simulação aleatória.
  É bem mais repetível que uma cidade com pedestres e trânsito.
- **Versão do jogo:** a Steam atualiza o tool sozinha. O `sessao.json` guarda a versão
  (`versao_jogo`, do JSON da volta) e o tamanho/data das DLLs da NVIDIA que vêm com ele.
  Compare entre sessões; se mudar no meio da pesquisa, registre.
- **Versão do DLSS** = a DLL do jogo. Com os overrides do NVIDIA App desligados, é a mesma em
  todas as máquinas com a mesma versão do tool.
- **Instrumentos diferentes por plataforma:** PresentMon (Windows) e MangoHud (Linux) não medem
  exatamente igual. Para Windows × Linux, compare o FPS por volta do tool; use o FPS de 5 s para
  tendências dentro de cada plataforma.
- **Aberturas do processo:** só testes com `execucoes = 1` (ou com poucos reinícios por
  travamento, que também são dado de aging) servem para concluir sobre envelhecimento do processo.
- O tool começa a contar FPS só quando a cena carrega; o `--aquecimento` do Mann-Kendall (30 min)
  e o `warmup_minutes` do relatório descartam o começo.

## 12. Solução de problemas

| Problema | O que fazer |
|---|---|
| `Benchmark Tool nao encontrado` | Instale pela Steam ou preencha `wukong.install_dir` |
| `GameUserSettings.ini ainda nao existe` | Abra o tool uma vez e saia pelo botão de sair |
| `Feche o Benchmark Tool antes` ao salvar perfil | O jogo só grava o arquivo ao sair; feche e salve o perfil |
| `O Benchmark Tool nao abriu` | A Steam precisa estar aberta e logada |
| Tela de shaders demora muito | Normal na 1ª abertura e depois de atualizar o driver. `startup_timeout_s` = 15 min |
| `nenhum FPS medido` (Windows) | PresentMon sem permissão: terminal como administrador ou grupo Performance Log Users |
| `nenhum FPS medido` (Linux) | Confira as opções de inicialização e a pasta `~/wukong_mangohud` |
| Cliques no lugar errado | Recalibre (passo 8) com a mesma resolução e modo de tela dos testes |
| A Steam atualizou o tool | Abra uma vez (shaders) e rode `validar` de novo antes da próxima bateria |
