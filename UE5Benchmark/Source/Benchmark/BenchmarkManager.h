// BenchmarkManager.h
// Versao modificada para testes de estresse longos (ex.: 48h) com DLSS.
//
// Parametros de linha de comando aceitos (todos opcionais):
//   -BenchPhase=03_dlss_fg          nome do teste (vira nome de arquivo)
//   -BenchDuration=172800           duracao em segundos (172800 = 48h)
//   -BenchOutDir=C:/runs/03_dlss_fg pasta onde os CSV/JSON sao gravados
//   -BenchInterval=5                intervalo de amostragem em segundos
//   -BenchCVars=r.A=1;r.B=0         console variables aplicadas no inicio
//   -BenchCameraSpeed=600           sobrescreve a velocidade da camera (cm/s)
//
// Sem esses parametros (ex.: rodando no Editor) ele usa os valores do painel Details.

#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "GameFramework/Actor.h"
#include "Misc/EngineVersion.h"
#include "BenchmarkManager.generated.h"

UCLASS()
class BENCHMARK_API ABenchmarkManager : public AActor
{
    GENERATED_BODY()

public:
    ABenchmarkManager();

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

public:
    virtual void Tick(float DeltaTime) override;

    // ---- Funcoes originais do projeto (mantidas para nao quebrar Blueprints) ----
    void SaveResultsToDisk();
    void CalculateAvgFPS();
    void OnBenchmarkComplete();
    void GetRendererDetails();
    bool bBenchmarkComplete;
    float CurrentFPS;

    UPROPERTY(BlueprintReadOnly, Category = "Benchmark Data")
    FString RendererName;
    UPROPERTY(BlueprintReadOnly, Category = "Benchmark Data")
    FString GPUName;
    UPROPERTY(BlueprintReadOnly, Category = "Benchmark Data")
    FString Resolution;
    UPROPERTY(BlueprintReadOnly, Category = "Benchmark Data")
    float AverageFPS;
    UFUNCTION(BlueprintCallable, Category = "Benchmark Data")
    float GetAverageFPS() const { return AverageFPS; }
    UFUNCTION(BlueprintCallable, Category = "Benchmark Data")
    FString GetBenchmarkSettings();

    UPROPERTY(EditAnywhere, Category = "UI")
    TSubclassOf<class UUserWidget> EndScreenWidgetClass;

    // ---- Configuracao do teste (valores padrao para quando roda no Editor) ----

    // Duracao do teste em segundos. Na linha de comando: -BenchDuration=
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Benchmark Config")
    float TestDurationSeconds = 300.0f;

    // Intervalo entre amostras gravadas no CSV. Na linha de comando: -BenchInterval=
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Benchmark Config")
    float SampleIntervalSeconds = 5.0f;

    // Fecha o jogo sozinho quando a duracao termina.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Benchmark Config")
    bool bQuitOnComplete = true;

    // Chamado pela camera a cada volta completa na spline.
    void OnLapComplete(int32 LapNumber);

    // Usados pelo HUD.
    FString GetPhaseTag() const { return PhaseTag; }
    double GetElapsedSeconds() const;
    int32 GetCurrentLap() const { return CurrentLap; }
    FString GetDLSSStatusLine() const;

private:
    TArray<float> FPSHistory; // original, nao e mais usado no modo continuo
    void DisplayEndScreenUI();

    void ReadCommandLine();
    void ApplyRequestedCVars();
    void WriteRunConfig();
    void WriteSample();
    void OnTestDurationElapsed();
    void AppendLine(const FString& FilePath, const FString& Line) const;

    FString PhaseTag;
    FString OutDir;
    FString SamplesPath;
    FString RequestedCVarsRaw;
    TArray<TPair<FString, FString>> RequestedCVars;

    double StartTimeSeconds = 0.0;
    int32 CurrentLap = 0;

    // Frame times (ms) acumulados desde a ultima amostra.
    TArray<float> WindowFrameTimesMs;

    FTimerHandle SampleTimer;
    FTimerHandle DurationTimer;
    FTimerHandle RunConfigTimer;

    // Estado do DLSS informado pelo plugin (preenchido em WriteRunConfig)
    FString SupportDLSS;
    FString SupportRR;
    FString SupportDLSSG;
    FString ActiveDLSSMode;
    FString ActiveDLSSGMode;
    float LastDLSSGFps = 0.f;
};