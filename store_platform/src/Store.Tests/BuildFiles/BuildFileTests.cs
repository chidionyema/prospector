using System.Xml.Linq;

namespace Store.Tests.Build;

/// <summary>
/// The build files must parse, and central package management must stay on.
/// </summary>
/// <remarks>
/// Written 2026-08-19, straight after a comment broke the build with no error naming it. An XML
/// comment may not contain two hyphens in a row, and the comment being added to
/// Directory.Packages.props quoted a command line with long flags. The file stopped parsing.
/// <para>
/// The failure does not name the broken file, and which wrong answer you get depends on which
/// command you run. Re-measured on 2026-08-19 by breaking the file on purpose:
/// </para>
/// <para>
/// `dotnet restore Store.sln` printed NU1604 "does not contain an inclusive lower bound" once
/// per centrally-versioned package, twenty-one of them across all three projects, and not one
/// line mentioning Directory.Packages.props. That is the output the original session read, and
/// it is why the diagnosis went to the packages instead of to the file. `dotnet build` on the
/// same broken tree DID name it, with MSB4024 and the exact line and column. So the file is not
/// unnameable; it is that restore runs first, fails first, and blames the dependencies.
/// </para>
/// <para>
/// The mechanism underneath is the same either way. MSBuild drops the file, that turns
/// ManagePackageVersionsCentrally off, and a PackageReference with no Version attribute has
/// nothing left to resolve against.
/// </para>
/// <para>
/// A test in THIS project cannot guard the parse. It was written that way first and proved
/// inert the same day: with the file malformed, `dotnet test --no-build --filter
/// EveryBuildPropsFileIsWellFormedXml` printed MSB4024 and nothing else, because MSBuild
/// refuses to evaluate Store.Tests.csproj when an import it needs will not load. The test
/// binary is never reached, so the assertion never runs. Both props files in this tree are
/// imported by every project, so there is no case left where it could have bitten.
/// </para>
/// <para>
/// The parse is guarded by the "MSBuild props files parse" step in the dotnet CI job instead,
/// which runs before `dotnet restore` and so is the only thing that CAN see it.
/// </para>
/// <para>
/// What is left here are the two checks a broken build cannot mask: the file parses fine and
/// somebody set a switch to false.
/// </para>
/// </remarks>
public class BuildFileTests
{
    private static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Store.sln")))
        {
            dir = dir.Parent;
        }

        Assert.NotNull(dir);
        return dir!.FullName;
    }

    [Fact]
    public void CentralPackageManagementIsOn()
    {
        var props = Path.Combine(RepoRoot(), "Directory.Packages.props");
        Assert.True(File.Exists(props), $"{props} is missing");

        var doc = XDocument.Load(props);
        var value = doc.Descendants()
            .FirstOrDefault(e => string.Equals(
                e.Name.LocalName, "ManagePackageVersionsCentrally", StringComparison.Ordinal))?.Value;

        Assert.True(
            string.Equals(value, "true", StringComparison.OrdinalIgnoreCase),
            "ManagePackageVersionsCentrally must stay true. With it off, every PackageReference "
            + "that omits a Version resolves to the oldest version on the feed, and the failure "
            + "names packages that are not the problem.");
    }

    [Fact]
    public void TransitivePinningIsOnSoAdvisoriesCanBePatched()
    {
        var props = Path.Combine(RepoRoot(), "Directory.Packages.props");
        var doc = XDocument.Load(props);
        var value = doc.Descendants()
            .FirstOrDefault(e => string.Equals(
                e.Name.LocalName, "CentralPackageTransitivePinningEnabled", StringComparison.Ordinal))?.Value;

        Assert.True(
            string.Equals(value, "true", StringComparison.OrdinalIgnoreCase),
            "CentralPackageTransitivePinningEnabled must stay true. Both advisories this repo has "
            + "had were in transitive packages: SQLitePCLRaw through EF Core, and OpenTelemetry "
            + "through Crux.Observability, which is on a local feed and will not ship a fix. "
            + "Without transitive pinning there is no way to patch either one.");
    }
}
