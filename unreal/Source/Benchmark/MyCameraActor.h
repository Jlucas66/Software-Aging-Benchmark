// MyCameraActor.h
// Camera que percorre uma spline. Versao modificada: em vez de parar no fim do
// percurso, volta ao inicio e continua (loop infinito), contando as voltas.

#pragma once

#include "CoreMinimal.h"
#include "Components/SplineComponent.h"
#include "Camera/CameraActor.h"
#include "BenchmarkManager.h"
#include "MyCameraActor.generated.h"

UCLASS()
class BENCHMARK_API AMyCameraActor : public ACameraActor
{
    GENERATED_BODY()

public:
    AMyCameraActor();

    virtual void Tick(float DeltaTime) override;

protected:
    virtual void BeginPlay() override;

public:
    // O gerenciador do benchmark (definido no nivel)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Benchmark Manager")
    ABenchmarkManager* BenchmarkMgr;

    // O ator que contem a spline (o percurso da camera)
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Camera Path")
    AActor* SplineActor;

    // Velocidade da camera ao longo da spline (cm/s). Na linha de comando: -BenchCameraSpeed=
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Camera Path")
    float CameraSpeed;

    // Numero de voltas completas no percurso
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Camera Path")
    int32 LapCount;

    UFUNCTION(BlueprintCallable, Category = "Benchmark Camera")
    void ActivateCamera();

private:
    float CurrentDistanceAlongSpline;
    USplineComponent* SplineComponent;
};
