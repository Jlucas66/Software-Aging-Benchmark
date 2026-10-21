// entrar na pasta e ativar o ambiente - Windows (PowerShell)
cd C:\Pesquisa\Software-Aging-Benchmark
.venv\Scripts\activate

// entrar na pasta e ativar o ambiente - Linux (terminal)
cd ~/Pesquisa/Software-Aging-Benchmark
source .venv/bin/activate

// so na primeira vez em cada maquina (cria o ambiente e instala as bibliotecas)
python -m venv .venv
pip install -r requirements.txt

ANTES DOS TESTES

// ver os 7 testes e as configuracoes de DLSS de cada um
python run.py list

// conferir se esta tudo instalado
python run.py check

RODAR OS TESTES

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

PLOTANDOS OS GRÁFICOS

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

PARA RODAR NO WINDOWS DO LABORATÓRIO

// em casa: copiar o jogo pronto para o HD externo/pendrive (troque E: pela letra dele)
robocopy C:\UE5BenchmarkBuild E:\UE5BenchmarkBuild /E

// no lab: copiar do HD externo para o mesmo caminho
robocopy E:\UE5BenchmarkBuild C:\UE5BenchmarkBuild /E

// no lab: baixar o projeto e preparar o Python
cd C:\
mkdir Pesquisa
cd Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

// no lab: so se o jogo reclamar de DLL faltando
C:\UE5BenchmarkBuild\Windows\Engine\Extras\Redist\en-us\UEPrereqSetup_x64.exe

// no lab: validar e rodar
// (no check, ignore os avisos de Unreal, Content e Plugins: nao sao usados para rodar)
python run.py check
python run.py run --tests 2 --minutes 3

// PREPARAR O LINUX 

// 1. driver proprietario da NVIDIA: conferir se esta instalado
nvidia-smi

// 2. umu-launcher (abre o Proton fora da Steam) - use a linha da sua distribuicao
sudo dnf install umu-launcher                 // Fedora
sudo pacman -S umu-launcher                   // Arch / CachyOS
sudo apt install ./umu-launcher_*.deb         // Ubuntu/Debian: baixe o .deb em
                                              // github.com/Open-Wine-Components/umu-launcher/releases

// 3. GE-Proton: baixe o .tar.gz em github.com/GloriousEggroll/proton-ge-custom/releases
mkdir -p ~/.local/share/Steam/compatibilitytools.d
tar -xf ~/Downloads/GE-Proton*.tar.gz -C ~/.local/share/Steam/compatibilitytools.d/
ls ~/.local/share/Steam/compatibilitytools.d/
// copie o nome da pasta que apareceu (ex.: GE-Proton10-20) para "proton_path"
// no bloco "linux" do config/bench.json

// 4. copiar o jogo do HD externo (troque NOME_DO_HD)
cp -r /media/$USER/NOME_DO_HD/UE5BenchmarkBuild ~/UE5BenchmarkBuild

// 5. projeto e Python (no Ubuntu, antes: sudo apt install python3-venv git)
mkdir -p ~/Pesquisa && cd ~/Pesquisa
git clone <url-do-repositorio> Software-Aging-Benchmark
cd Software-Aging-Benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

// 6. conferir e validar (a 1a abertura cria o prefixo do Wine e pode demorar;
//    se der "tempo limite", rode de novo)
python run.py check
python run.py run --tests 2 --minutes 3