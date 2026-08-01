using FluentValidation;
using MediatR;
using Store.Api.Common;

namespace Store.Api.Common;

/// <summary>
/// MediatR pipeline behavior that runs FluentValidation before the handler.
/// On failure, returns a failed Result&lt;T&gt; (mapped to HTTP 400) when the
/// response is a Result type; otherwise throws. Ported from haworks
/// BuildingBlocks/Behaviors/ValidationBehavior.cs.
/// </summary>
public sealed class ValidationBehavior<TRequest, TResponse> : IPipelineBehavior<TRequest, TResponse>
    where TRequest : IRequest<TResponse>
{
    private readonly IEnumerable<IValidator<TRequest>> _validators;

    public ValidationBehavior(IEnumerable<IValidator<TRequest>> validators) => _validators = validators;

    public async Task<TResponse> Handle(TRequest request, RequestHandlerDelegate<TResponse> next, CancellationToken cancellationToken)
    {
        if (!_validators.Any())
            return await next().ConfigureAwait(false);

        var context = new ValidationContext<TRequest>(request);
        var failures = (await Task.WhenAll(_validators.Select(v => v.ValidateAsync(context, cancellationToken))).ConfigureAwait(false))
            .SelectMany(r => r.Errors)
            .Where(f => f is not null)
            .ToList();

        if (failures.Count == 0)
            return await next().ConfigureAwait(false);

        var message = string.Join("; ", failures.Select(f => f.ErrorMessage));
        var responseType = typeof(TResponse);

        if (responseType.IsGenericType && responseType.GetGenericTypeDefinition() == typeof(Result<>))
        {
            var error = Error.Validation("Validation.Failed", message);
            var failureMethod = typeof(Result)
                .GetMethod(nameof(Result.Failure), 1, new[] { typeof(Error) })!
                .MakeGenericMethod(responseType.GetGenericArguments()[0]);
            return (TResponse)failureMethod.Invoke(null, System.Reflection.BindingFlags.DoNotWrapExceptions, null, new object[] { error }, null)!;
        }

        if (responseType == typeof(Result))
            return (TResponse)(object)Result.Failure(Error.Validation("Validation.Failed", message));

        throw new ValidationException(failures);
    }
}
