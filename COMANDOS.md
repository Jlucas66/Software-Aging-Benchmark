# Comandos

Rode tudo de dentro da pasta do projeto, com o ambiente Python ativo
(o começo da linha deve mostrar `(.venv)`).

```
// entrar na pasta e ativar o ambiente - Windows (PowerShell)
cd C:\Pesquisa\Software-Aging-Benchmark
.venv\Scripts\activate

// entrar na pasta e ativar o ambiente - Linux (terminal)
cd ~/Pesquisa/Software-Aging-Benchmark
source .venv/bin/activate

// so na primeira vez em cada maquina (cria o ambiente e instala as bibliotecas)
python -m venv .venv
pip install -r requirements.txt
```

## Antes de testar

```
// ver os 7 testes e as configuracoes de DLSS de cada um
python run.py list

// conferir se esta tudo instalado
python run.py check
```

## Rodar testes

```
// validacao rapida (3 min)
python run.py run --tests 2 --minutes 3

// um teste por vez, 8 h
python run.py run --tests 1 --hours 8
python run.py run --tests 2 --hours 8

// varios testes em sequencia (pausa de 10 min entre eles)
python run.py run --tests 1,2 --hours 8

// bateria completa, 48 h cada
python run.py run --tests all --hours 48

// interromper: Ctrl+C (os dados ja gravados ficam salvos)
```

## Gráficos e análise

```
// graficos e resumo da sessao mais recente
python run.py report

// de uma sessao especifica
python run.py report BenchmarkRuns/2026-10-21_09-30_windows

// juntando todas as sessoes (ex.: um teste por sessao)
python run.py report --all-sessions

// Mann-Kendall de todas as sessoes (testes longos)
python mann_kendall.py

// Mann-Kendall de testes curtos (sem aquecimento e sem janela)
python mann_kendall.py --aquecimento 0 --janela 0
```

## Só no Windows

```
// compilar e gerar o .exe (apenas quando mudar o C++ ou os plugins)
python run.py build
python run.py package
```

## Preparar outra máquina Windows (ex.: laboratório)

Passo a passo completo no `INSTALACAO.md`. Resumo:

```
// projeto e Python
cd C:\
mkdir Pesquisa
cd Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

// o jogo: compilar aqui (Caminho A) ...
// (instale Unreal 5.4 + Build Tools; copie Content e Plugins - INSTALACAO.md, secao 2.3)
python run.py check
python run.py build
python run.py package

// ... ou baixar o jogo pronto da release "jogo-v1" do GitHub (Caminho B) e extrair
& "C:\Program Files\7-Zip\7z.exe" x $env:USERPROFILE\Downloads\UE5BenchmarkBuild.7z.001 -oC:\

// enviar o jogo pronto para o GitHub (uma vez, na maquina que ja tem o jogo):
// gera partes de 1,9 GB em C:\Temp; depois anexe todas numa release do GitHub
& "C:\Program Files\7-Zip\7z.exe" a -v1900m C:\Temp\UE5BenchmarkBuild.7z C:\UE5BenchmarkBuild

// validar
python run.py check
python run.py run --tests all --minutes 3
```

## Salvar no GitHub

```
git add -A
git status
git commit -m "descricao"
git push
```

## Preparar o Linux (uma vez só) - Zorin OS / Ubuntu

No Linux roda o mesmo jogo compilado no Windows, pelo Proton. Não precisa da Unreal.
Antes de sair do Windows: faça commit/push do projeto e desligue a "Inicialização rápida"
(Painel de Controle → Opções de Energia), senão o Linux não abre a partição do Windows.

```
// 1. driver da NVIDIA: menu do Zorin → "Drivers adicionais" → escolha o driver
//    nvidia-driver mais novo marcado como "proprietário, testado" → aplicar → reiniciar
nvidia-smi
ls /usr/lib/x86_64-linux-gnu/nvidia/wine/      // deve listar nvngx.dll (DLSS no Proton)

// 2. pacotes basicos
sudo apt update
sudo apt install -y git python3-venv python3-pip p7zip-full

// 3. GE-Proton: no navegador, baixe o GE-ProtonXX-YY.tar.gz em
//    github.com/GloriousEggroll/proton-ge-custom/releases
mkdir -p ~/.local/share/Steam/compatibilitytools.d
tar -xf ~/Downloads/GE-Proton*.tar.gz -C ~/.local/share/Steam/compatibilitytools.d/
ls ~/.local/share/Steam/compatibilitytools.d/
// copie o nome da pasta (ex.: GE-Proton10-20) para "proton_path" no bloco "linux"
// do config/bench.json

// 4. umu-launcher: no navegador, baixe o arquivo que termina em -zipapp.tar em
//    github.com/Open-Wine-Components/umu-launcher/releases
tar -xf ~/Downloads/umu-launcher-*-zipapp.tar -C ~/.local/share/
ls ~/.local/share/umu/                       // deve listar umu-run

// 5. o jogo: da particao do Windows da mesma maquina (abra o disco no app Arquivos
//    para montar e veja o nome dele) ...
ls /media/$USER/
rsync -a --info=progress2 "/media/$USER/NOME_DO_DISCO/UE5BenchmarkBuild" ~/
//    ... ou da release "jogo-v1" do GitHub (baixe todas as partes; sudo apt install p7zip-full)
7z x ~/Downloads/UE5BenchmarkBuild.7z.001 -o$HOME
ls ~/UE5BenchmarkBuild/Windows/Benchmark/Binaries/Win64/   // deve listar Benchmark.exe

// 6. projeto e Python
mkdir -p ~/Pesquisa && cd ~/Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

// 7. conferir e validar (a 1a abertura baixa o Steam Runtime, cria o prefixo do Wine
//    e compila shaders: pode demorar e dar "tempo limite"; se der, rode de novo)
python run.py check
python run.py run --tests 2 --minutes 3
```

Depois disso, os comandos de rodar testes, gráficos e análise são os mesmos do Windows.
Antes de testes longos: Configurações → Energia → "Tela em branco" = Nunca e
"Suspensão automática" desligada.