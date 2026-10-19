// MyCameraActor.cpp
// Versao modificada: loop continuo pela spline.

#include "MyCameraActor.h"
#include "Components/SplineComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

AMyCameraActor::AMyCameraActor()
{
    PrimaryActorTick.bCanEverTick = true;
    CameraSpeed = 2.f;
    CurrentDistanceAlongSpline = 0.f;
    LapCount = 0;
    BenchmarkMgr = nullptr;
    SplineActor = nullptr;
    SplineComponent = nullptr;
}

void AMyCameraActor::BeginPlay()
{
    Super::BeginPlay();

    // Velocidade opcional vinda da linha de comando
    float SpeedFromCommandLine = 0.f;
    if (FParse::Value(FCommandLine::Get(), TEXT("BenchCameraSpeed="), SpeedFromCommandLine) && SpeedFromCommandLine > 0.f)
    {
        CameraSpeed = SpeedFromCommandLine;
    }

    if (SplineActor)
    {
        SplineComponent = Cast<USplineComponent>(SplineActor->GetComponentByClass(USplineComponent::StaticClass()));
        if (SplineComponent)
        {
            UE_LOG(LogTemp, Log, TEXT("[Bench] Spline encontrada, comprimento %.0f cm, velocidade %.1f cm/s (uma volta ~%.0f s)"),
                SplineComponent->GetSplineLength(), CameraSpeed,
                CameraSpeed > 0.f ? SplineComponent->GetSplineLength() / CameraSpeed : 0.f);
        }
        else
        {
            UE_LOG(LogTemp, Error, TEXT("Failed to find SplineComponent on assigned SplineActor."));
        }
    }
    else
    {
        UE_LOG(LogTemp, Error, TEXT("SplineActor not assigned in the editor."));
    }

    ActivateCamera();
}

void AMyCameraActor::ActivateCamera()
{
    APlayerController* PlayerController = UGameplayStatics::GetPlayerController(GetWorld(), 0);
    if (PlayerController)
    {
        PlayerController->SetViewTargetWithBlend(this, 0.0f);
    }
    else
    {
        UE_LOG(LogTemp, Error, TEXT("Player controller not ready!"));
    }
}

void AMyCameraActor::Tick(float DeltaTime)
{
    Super::Tick(DeltaTime);

    if (!SplineComponent)
    {
        return;
    }

    const float SplineLength = SplineComponent->GetSplineLength();
    if (SplineLength <= 0.f)
    {
        return;
    }

    CurrentDistanceAlongSpline += CameraSpeed * DeltaTime;

    // Chegou ao fim do percurso: volta ao inicio e continua (antes, a camera parava aqui).
    if (CurrentDistanceAlongSpline > SplineLength)
    {
        CurrentDistanceAlongSpline = FMath::Fmod(CurrentDistanceAlongSpline, SplineLength);
        ++LapCount;

        if (BenchmarkMgr)
        {
            BenchmarkMgr->OnLapComplete(LapCount);
        }
        else
        {
            UE_LOG(LogTemp, Warning, TEXT("BenchmarkMgr reference is not set in MyCameraActor!"));
        }
    }

    const FVector NewLocation = SplineComponent->GetLocationAtDistanceAlongSpline(CurrentDistanceAlongSpline, ESplineCoordinateSpace::World);
    const FRotator NewRotation = SplineComponent->GetRotationAtDistanceAlongSpline(CurrentDistanceAlongSpline, ESplineCoordinateSpace::World);
    SetActorLocation(NewLocation);
    SetActorRotation(NewRotation);
}
