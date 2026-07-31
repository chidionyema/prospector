using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class AddPackStorefrontMetadata : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "EffortTag",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "FinancialSnapshotJson",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Headline",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ProofPoint",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "QaVerdictSummary",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "SampleExtractJson",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "SourceCount",
                table: "Packs",
                type: "INTEGER",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Subhead",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "TimeToFirstRevenue",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "VerifiedAt",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "WhatYouGetJson",
                table: "Packs",
                type: "TEXT",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "WhoPays",
                table: "Packs",
                type: "TEXT",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "EffortTag",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "FinancialSnapshotJson",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Headline",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "ProofPoint",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "QaVerdictSummary",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "SampleExtractJson",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "SourceCount",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "Subhead",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "TimeToFirstRevenue",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "VerifiedAt",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "WhatYouGetJson",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "WhoPays",
                table: "Packs");
        }
    }
}
